import io
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import analytics as an
from app import service
from app.db import get_engine
from app.incentive import compute, resolve_plan
from app.main import create_app
from app.profile import effective_economics, get_profile, tier_name, tokens
from app.uploader import (UploadError, _month_of, build_dataset, import_upload, read_table, save_upload, spec,
                          suggest_mapping, template_csv)

MAP = {"hcp_id": "NPI", "month": "Period", "trx": "Scripts", "calls": "Visits"}


def make_df(n=40, months=18, seed=1, with_tier=False, with_territory=False, third=False):
    rng = np.random.default_rng(seed)
    periods = pd.period_range("2024-01", periods=months, freq="M")
    rows = []
    for i in range(n):
        pot = rng.lognormal(1.5, 0.4)
        for t, p in enumerate(periods):
            v = int(rng.poisson(3))
            r = {"NPI": str(5000000000 + i), "Period": p.strftime("%b-%Y"), "Scripts": int(rng.poisson(pot * (1 + 0.1 * np.log1p(v)))), "Visits": v}
            if with_tier:
                r["Class"] = ["Gold", "Silver"][i % 2]
            if with_territory:
                r["Terr"] = f"T{i % 4}"
                r["Region"] = "East" if i % 4 < 2 else "West"
            if third:
                r["Mails"] = int(rng.poisson(2))
            rows.append(r)
    return pd.DataFrame(rows).astype(str)


def build(settings, df, mapping=None, options=None):
    return build_dataset(settings, df, mapping or MAP, options)


# ---------- mapping suggestions and parsing ----------
def test_suggest_mapping_recognises_common_headers():
    cols = ["NPI", "Prescriber", "State", "Specialty Group", "Period", "NBRx", "Detail Visits", "Sample Drops", "Email Sends", "Territory", "Rep", "Notes"]
    m = suggest_mapping(cols)
    assert m == {"hcp_id": "NPI", "month": "Period", "trx": "NBRx", "calls": "Detail Visits", "samples": "Sample Drops", "emails": "Email Sends",
                 "hcp_name": "Prescriber", "region": "State", "specialty": "Specialty Group", "territory": "Territory", "rep": "Rep"}
    assert len(set(m.values())) == len(m)                  # a column is never used twice
    assert suggest_mapping(["alpha", "beta"]) == {}


@pytest.mark.parametrize("value,expected", [
    ("Jul-2024", "2024-07"), ("2024-07", "2024-07"), ("07/2024", "2024-07"), ("202407", "2024-07"), ("2024-07-15", "2024-07"),
    ("2024/7/1", "2024-07"), ("45474", "2024-07"), ("2024-07-01 00:00:00", "2024-07"), ("July 2024", "2024-07"),
    ("2024-13", None), ("13/2024", None), ("abc", None), ("1850-01", None), ("", None)])
def test_month_parsing(value, expected):
    assert _month_of(value) == expected


def test_template_matches_spec(settings):
    header = template_csv().splitlines()[0].split(",")
    assert header == [r["key"] for r in spec(settings)["roles"]]
    assert {r["key"] for r in spec(settings)["roles"] if r["required"]} == {"hcp_id", "month", "trx", "calls"}


# ---------- validation errors ----------
def test_required_mapping_and_unknown_fields(settings):
    df = make_df()
    with pytest.raises(UploadError) as e:
        build(settings, df, {"hcp_id": "NPI", "month": "Period"})
    assert any("Prescriptions" in i for i in e.value.issues) and any("Main promotion channel" in i for i in e.value.issues)
    with pytest.raises(UploadError, match="mapping"):
        build(settings, df, {**MAP, "bogus": "NPI"})
    with pytest.raises(UploadError) as e:
        build(settings, df, {**MAP, "emails": "Visits"})
    assert any("more than one field" in i for i in e.value.issues)
    with pytest.raises(UploadError) as e:
        build(settings, df, {**MAP, "region": "Nope"})
    assert any("not in the file" in i for i in e.value.issues)


def test_bad_values_report_row_numbers(settings):
    df = make_df()
    df.loc[2, "Period"] = "not a month"
    df.loc[5, "Scripts"] = "abc"
    df.loc[7, "Visits"] = "-3"
    with pytest.raises(UploadError) as e:
        build(settings, df)
    text_ = " ".join(e.value.issues)
    assert "file rows 4" in text_ and "file rows 7" in text_ and "file rows 9" in text_ and "negative" in text_


def test_blank_ids_and_empty_outcomes(settings):
    df = make_df()
    df.loc[0, "NPI"] = ""
    with pytest.raises(UploadError, match="data problems"):
        build(settings, df)
    df = make_df()
    df["Scripts"] = "0"
    with pytest.raises(UploadError, match="All prescription values"):
        build(settings, df)
    df = make_df()
    df["Visits"] = "0"
    with pytest.raises(UploadError, match="all 0"):
        build(settings, df)


def test_calendar_gap_and_too_short(settings):
    df = make_df()
    df = df[df["Period"] != "Mar-2024"]
    with pytest.raises(UploadError) as e:
        build(settings, df)
    assert "2024-03" in e.value.issues[0]
    with pytest.raises(UploadError, match="At least 4 months"):
        build(settings, make_df(months=3))


def test_limits_come_from_config(settings):
    tight = replace(settings, upload={**settings.upload, "max_hcps": 10})
    with pytest.raises(UploadError, match="limit is 10"):
        build(tight, make_df(n=40))
    few_tiers = replace(settings, upload={**settings.upload, "max_tiers": 1})
    with pytest.raises(UploadError, match="Too many tier"):
        build(few_tiers, make_df(with_tier=True), {**MAP, "tier": "Class"})


# ---------- policies ----------
def test_duplicate_policy(settings):
    df = pd.concat([make_df(), make_df().head(3)], ignore_index=True)
    ok = build(settings, df)
    assert any("duplicate" in w for w in ok["profile"]["warnings"])
    assert len(ok["rx"]) == 40 * 18
    with pytest.raises(UploadError, match="Duplicate"):
        build(settings, df, options={"duplicates": "error"})


def test_missing_policy(settings):
    df = make_df().drop([10, 11, 200])
    zero = build(settings, df)
    assert len(zero["rx"]) == 40 * 18 and any("set to 0" in w for w in zero["profile"]["warnings"])
    excl = build(settings, df, options={"missing": "exclude"})
    assert excl["summary"]["hcps"] == 40 - 2 and len(excl["rx"]) == 38 * 18
    with pytest.raises(UploadError, match="complete"):
        build(settings, df, options={"missing": "error"})
    with pytest.raises(UploadError, match="Invalid option"):
        build(settings, df, options={"missing": "guess"})


# ---------- transformation ----------
def test_ids_names_and_default_dimensions(settings):
    b = build(settings, make_df())
    hcp = b["hcp"]
    assert hcp["external_id"].iloc[0] == "5000000000" and hcp["hcp_id"].tolist() == list(range(1, 41))
    assert (hcp["name"] == hcp["external_id"]).all()                    # no name column: the ID is shown
    assert set(hcp["region"]) == {"All"} and set(hcp["specialty"]) == {"All"}


def test_tier_derived_from_volume_when_absent(settings):
    b = build(settings, make_df(n=100))
    tiers = b["hcp"].assign(total=b["rx"].groupby("hcp_id")["trx"].sum().reindex(b["hcp"]["hcp_id"]).to_numpy())
    counts = tiers["tier"].value_counts().to_dict()
    shares = settings.upload["derived_tier_shares"]
    assert counts == {k: int(round(v * 100)) for k, v in shares.items()}
    assert tiers.groupby("tier")["total"].mean().sort_values(ascending=False).index.tolist() == list(shares)
    assert "tier" in b["profile"]["derived"] and any("derived" in w for w in b["profile"]["warnings"])


def test_supplied_tier_territory_and_region(settings):
    b = build(settings, make_df(with_tier=True, with_territory=True), {**MAP, "tier": "Class", "territory": "Terr", "region": "Region"})
    assert set(b["hcp"]["tier"]) == {"Gold", "Silver"} and b["profile"]["derived"] == []
    terr = b["territory"]
    assert len(terr) == 4 and set(terr["region"]) == {"East", "West"}
    assert b["hcp"]["territory_id"].notna().all() and set(terr["rep_name"]) == {f"Rep T{i}" for i in range(4)}


def test_channels_labels_and_economics(settings):
    b = build(settings, make_df(third=True), {**MAP, "emails": "Mails"},
              {"labels": {"entity": "Prescriber", "metric": "NBRx", "channels": {"calls": "Detail visits"}},
               "economics": {"revenue_per_trx": "300", "cost_per_call": 100}, "name": "My brand"})
    p = b["profile"]
    ch = {c["key"]: c for c in p["channels"]}
    assert ch["calls"]["label"] == "Detail visits" and ch["calls"]["unit"] == "detail visit"
    assert ch["emails"]["active"] and not ch["samples"]["active"]
    assert p["labels"]["entity"] == "Prescriber" and p["labels"]["entities"] == "Prescribers" and p["labels"]["metric"] == "NBRx"
    assert p["economics"] == {"revenue_per_trx": 300.0, "cost_per_call": 100.0} and p["name"] == "My brand"
    for bad in ({"revenue_per_trx": 0}, {"cost_per_call": -1}, {"cost_per_sample": "x"}):
        with pytest.raises(UploadError, match="economics"):
            build(settings, make_df(), options={"economics": bad})


def test_tier_name_helper(settings):
    from app.profile import default_profile
    p = default_profile(settings)
    assert tier_name(p, "A") == "Tier A" and tier_name(p, "Platinum") == "Platinum"
    assert tokens(p)["primary_l"] == "calls" and tokens(p)["metric"] == "Rx"


# ---------- reading files ----------
def test_read_csv_variants(settings, tmp_path):
    df = make_df(n=5, months=4)
    semi = tmp_path / "semi.csv"
    semi.write_text(df.to_csv(index=False, sep=";"), encoding="latin-1")
    assert list(read_table(settings, semi).columns) == list(df.columns)
    bom = tmp_path / "bom.csv"
    bom.write_bytes(b"\xef\xbb\xbf" + df.to_csv(index=False).encode())
    assert list(read_table(settings, bom).columns)[0] == "NPI"
    dup = tmp_path / "dup.csv"
    dup.write_text("a,a\n1,2\n")
    with pytest.raises(UploadError, match="Duplicate column"):
        read_table(settings, dup)
    hdr = tmp_path / "hdr.csv"
    hdr.write_text("a,,c\n1,2,3\n")
    with pytest.raises(UploadError, match="header"):
        read_table(settings, hdr)
    empty = tmp_path / "empty.csv"
    empty.write_text("a,b\n")
    with pytest.raises(UploadError, match="no data rows"):
        read_table(settings, empty)


def test_save_upload_guards(settings, tmp_path):
    small = replace(settings, upload={**settings.upload, "dir": str(tmp_path), "max_mb": 1})
    with pytest.raises(UploadError, match="Unsupported"):
        save_upload(small, "x.exe", b"abc")
    with pytest.raises(UploadError, match="empty"):
        save_upload(small, "x.csv", b"")
    with pytest.raises(UploadError, match="larger"):
        save_upload(small, "x.csv", b"a" * (1024 * 1024 + 1))
    uid = save_upload(small, "../../evil name.csv", b"a,b\n1,2\n")
    saved = list((tmp_path / uid).iterdir())
    assert len(saved) == 1 and saved[0].name == "evil_name.csv"          # path components stripped
    with pytest.raises(UploadError, match="Unknown upload"):
        import_upload(small, "../../etc", MAP)


# ---------- end to end into PostgreSQL ----------
@pytest.fixture()
def upload_settings(scratch_settings, tmp_path):
    return replace(scratch_settings, upload={**scratch_settings.upload, "dir": str(tmp_path / "uploads")})


def test_import_excel_end_to_end(upload_settings):
    df = make_df(n=40, months=18, with_tier=True, with_territory=True, third=True)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    uid = save_upload(upload_settings, "brand.xlsx", buf.getvalue())
    mapping = {**MAP, "tier": "Class", "territory": "Terr", "region": "Region", "emails": "Mails"}
    res = import_upload(upload_settings, uid, mapping, {"labels": {"entity": "Account", "metric": "Units"}, "economics": {"revenue_per_trx": 250}})
    assert res["summary"]["hcps"] == 40 and res["summary"]["territories"] == 4

    prof = get_profile(upload_settings)
    assert prof["kind"] == "upload" and prof["labels"]["entity"] == "Account"
    assert {d["key"]: d["active"] for d in prof["dimensions"]} == {"region": True, "specialty": False, "tier": True}
    assert effective_economics(upload_settings)["revenue_per_trx"] == 250 and effective_economics(upload_settings)["cost_per_call"] == upload_settings.economics["cost_per_call"]
    with get_engine(upload_settings).connect() as c:
        assert c.execute(text("SELECT external_id FROM hcp ORDER BY hcp_id LIMIT 1")).scalar() == "5000000000"   # > int32 ids survive

    f = an.Filters()
    assert an.kpis(upload_settings, f)["active_hcps"] == 40
    model, _ = service.get_model(upload_settings, f)
    assert set(model.tier_beta) == {"Gold", "Silver"} and model.channels_used == ["emails"]
    roi = service.get_roi(upload_settings, f)
    assert {(r["channel"]) for r in roi} == {"calls", "emails"}              # samples absent -> not analysed
    assert service.get_optimization(upload_settings, f, 0)["summary"]["recommended_calls"] > 0
    assert service.get_targeting(upload_settings, f)["summary"]["hcps"] == 40
    ic = compute(upload_settings, resolve_plan(upload_settings))
    assert ic["summary"]["territories"] == 4 and ic["quarters"]
    insights = " ".join(service.build_report(upload_settings, f)["insights"])
    assert "Account" in insights and "Units" in insights and "Rx" not in insights


def test_failed_import_keeps_previous_data(upload_settings):
    good = save_upload(upload_settings, "good.csv", make_df(n=40).to_csv(index=False).encode())
    import_upload(upload_settings, good, MAP)
    before = an.kpis(upload_settings, an.Filters())["total_trx"]
    bad = make_df(n=40)
    bad.loc[3, "Scripts"] = "oops"
    uid = save_upload(upload_settings, "bad.csv", bad.to_csv(index=False).encode())
    with pytest.raises(UploadError):
        import_upload(upload_settings, uid, MAP)
    assert an.kpis(upload_settings, an.Filters())["total_trx"] == before


# ---------- API ----------
@pytest.fixture()
def api(upload_settings):
    return TestClient(create_app(upload_settings))


def test_api_spec_template_and_meta(api):
    s = api.get("/api/upload/spec").json()
    assert [r["key"] for r in s["roles"]][:4] == ["hcp_id", "month", "trx", "calls"] and s["options"][1]["key"] == "missing"
    t = api.get("/api/upload/template")
    assert t.status_code == 200 and t.text.startswith("hcp_id,month,trx,calls")
    m = api.get("/api/meta").json()
    assert m["profile"]["kind"] == "synthetic" and m["profile"]["labels"]["metric"] == "Rx"


def test_api_upload_flow_and_reset(api):
    csv_bytes = make_df(n=40, with_tier=True).to_csv(index=False).encode()
    r = api.post("/api/upload/inspect", files={"file": ("brand.csv", csv_bytes, "text/csv")})
    assert r.status_code == 200
    info = r.json()
    assert info["rows"] == 40 * 18 and info["suggested"]["hcp_id"] == "NPI" and info["suggested"]["tier"] == "Class"
    assert {c["name"] for c in info["columns"]} == {"NPI", "Period", "Scripts", "Visits", "Class"}
    mapping = {"hcp_id": "NPI", "month": "Period", "trx": "Scripts", "calls": "Visits", "tier": "Class"}
    r = api.post("/api/upload/import", json={"upload_id": info["upload_id"], "mapping": mapping,
                                              "options": {"labels": {"metric": "NBRx", "channels": {"calls": "Detail visits"}}}})
    assert r.status_code == 200 and r.json()["summary"]["hcps"] == 40
    meta = api.get("/api/meta").json()
    assert meta["profile"]["labels"]["metric"] == "NBRx" and meta["tiers"] == ["Gold", "Silver"]
    assert api.get("/api/kpis").json()["active_hcps"] == 40
    assert api.get("/api/hcps").json()["total"] == 40
    assert api.get("/api/incentive").status_code == 422                    # no territory column mapped
    assert "territory" in api.get("/api/incentive").json()["detail"].lower()
    di = api.get("/api/data-info").json()
    assert di["history"][0]["name"] == "brand.csv" and di["profile"]["labels"]["metric"] == "NBRx"
    r = api.post("/api/data/reset-sample")
    assert r.status_code == 200 and api.get("/api/meta").json()["profile"]["kind"] == "synthetic"


def test_api_upload_errors(api):
    r = api.post("/api/upload/inspect", files={"file": ("x.exe", b"abc", "application/octet-stream")})
    assert r.status_code == 422 and "Unsupported" in r.json()["detail"]["message"]
    info = api.post("/api/upload/inspect", files={"file": ("a.csv", make_df(n=40).to_csv(index=False).encode(), "text/csv")}).json()
    r = api.post("/api/upload/import", json={"upload_id": info["upload_id"], "mapping": {"hcp_id": "NPI"}})
    d = r.json()["detail"]
    assert r.status_code == 422 and d["message"] and len(d["issues"]) >= 3
    assert api.post("/api/upload/import", json={"upload_id": "nope", "mapping": {}}).status_code == 422
    assert api.post("/api/upload/import", json={"upload_id": info["upload_id"], "mapping": "x"}).status_code == 422


# ---------- the sample extract that ships with the repo ----------
def test_sample_extract_maps_and_imports(upload_settings):
    from pathlib import Path
    from app.uploader import inspect
    sample = Path(__file__).resolve().parent.parent / "samples" / "lipidex_prescriber_extract.csv"
    uid = save_upload(upload_settings, sample.name, sample.read_bytes())
    info = inspect(upload_settings, uid)
    assert info["rows"] == 7490 and len(info["suggested"]) == 12            # every column recognised without help
    assert info["suggested"]["tier"] == "Segment" and info["suggested"]["hcp_id"] == "NPI" and info["suggested"]["month"] == "Reporting Month"
    res = import_upload(upload_settings, uid, info["suggested"], {"missing": "exclude"})
    assert res["summary"] == {"hcps": 355, "months": 18, "first_month": "2024-07", "last_month": "2025-12",
                              "rows_in_file": 7490, "rows_loaded": 6390, "territories": 28}
    joined = " ".join(res["warnings"])
    assert "25 blank" in joined and "6 duplicate" in joined and "65 prescriber(s) with missing months" in joined
    prof = get_profile(upload_settings)
    assert prof["labels"]["metric"] == "Total Rx" and prof["channels"][0]["label"] == "Detail Visits"      # defaults to the file's own headers
    assert {d["key"]: d["values"] for d in prof["dimensions"]} == {"region": 7, "specialty": 3, "tier": 4}
    f = an.Filters()
    model, _ = service.get_model(upload_settings, f)
    assert set(model.tier_beta) == {"Platinum", "Gold", "Silver", "Bronze"}
    assert compute(upload_settings, resolve_plan(upload_settings))["quarters"] == ["2025-Q3", "2025-Q4"]
