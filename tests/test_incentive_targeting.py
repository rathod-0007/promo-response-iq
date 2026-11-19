import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from app import analytics as an
from app import service
from app.datagen import generate, make_territories
from app.db import get_engine
from app.importer import ImportError_, import_csv_dir
from app.incentive import IncentiveError, compute, payout_fraction, resolve_plan
from app.targeting import analyze

PLAN = {"threshold_attainment": 0.8, "threshold_payout": 0.5, "accelerator": 1.5, "cap_payout": 2.0}


# ---------- payout curve ----------
def test_payout_curve_key_points():
    f = payout_fraction([0.5, 0.79, 0.8, 0.9, 1.0, 1.1, 1.5, 3.0], PLAN)
    assert f.tolist() == pytest.approx([0.0, 0.0, 0.5, 0.75, 1.0, 1.15, 1.75, 2.0])


def test_payout_curve_is_monotonic_and_capped():
    xs = np.linspace(0, 3, 301)
    f = payout_fraction(xs, PLAN)
    assert (np.diff(f) >= -1e-12).all() and f.max() == 2.0 and f.min() == 0.0


def test_resolve_plan_defaults_overrides_and_validation(settings):
    base = resolve_plan(settings)
    assert base["accelerator"] == settings.incentive["accelerator"]
    assert resolve_plan(settings, {"accelerator": 2.0, "cap_payout": None})["accelerator"] == 2.0
    for bad in ({"accelerator": 99}, {"threshold_attainment": 1.0}, {"quota_growth_pct": -80}, {"nope": 1}):
        with pytest.raises(IncentiveError):
            resolve_plan(settings, bad)


# ---------- data model ----------
def test_territories_cover_regions_and_are_balanced(settings):
    sim = settings.simulation
    hcp, _, _ = generate(sim)
    terr = make_territories(sim)
    assert len(terr) == len(sim["regions"]) * sim["territories_per_region"]
    merged = hcp.merge(terr, on="territory_id", suffixes=("", "_t"))
    assert len(merged) == len(hcp) and (merged["region"] == merged["region_t"]).all()
    counts = merged.groupby(["region", "territory_id"]).size().groupby("region").agg(["min", "max"])
    assert ((counts["max"] - counts["min"]) <= 1).all()


def test_generation_is_unchanged_by_territories(settings):
    a, b = generate(settings.simulation), generate(settings.simulation)
    assert a[0].equals(b[0]) and a[2].equals(b[2])


# ---------- incentive compensation ----------
def test_incentive_reconciles_with_sql(settings):
    plan = resolve_plan(settings)
    res = compute(settings, plan)
    row = res["territories"][0]
    q = res["quarter"]
    year, qn = int(q[:4]), int(q[-1])

    def quarter_rx(y):
        months = [f"{y}-{3 * (qn - 1) + k:02d}" for k in (1, 2, 3)]
        with get_engine(settings).connect() as c:
            return float(c.execute(text("SELECT SUM(trx) FROM v_territory_month WHERE territory = :t AND month = ANY(:m)"),
                             {"t": row["territory"], "m": months}).scalar())

    assert row["actual"] == quarter_rx(year)
    assert row["quota"] == pytest.approx(round(quarter_rx(year - 1) * (1 + plan["quota_growth_pct"] / 100)), abs=1)
    assert row["attainment_pct"] == pytest.approx(row["actual"] / row["quota"] * 100, abs=0.5)  # quota is displayed rounded
    expected = float(payout_fraction(row["attainment_pct"] / 100, plan)) * plan["target_incentive"]
    assert row["payout"] == pytest.approx(expected, abs=plan["target_incentive"] * 0.002)


def test_incentive_summary_is_internally_consistent(settings):
    res = compute(settings, resolve_plan(settings))
    s = res["summary"]
    assert sum(r["total_payout"] for r in res["by_quarter"]) == pytest.approx(s["total_payout"], abs=len(res["by_quarter"]))
    assert s["territory_quarters"] == s["territories"] * s["quarters"]
    assert sum(b["count"] for b in res["histogram"]) == s["territory_quarters"]
    assert len(res["territories"]) == s["territories"]
    assert res["curve"][0]["payout_pct"] == 0 and max(c["payout_pct"] for c in res["curve"]) <= res["plan"]["cap_payout"] * 100


def test_incentive_filters_and_quarter_choice(settings):
    all_ = compute(settings, resolve_plan(settings))
    west = compute(settings, resolve_plan(settings), region="West")
    assert 0 < len(west["territories"]) < len(all_["territories"]) and {t["region"] for t in west["territories"]} == {"West"}
    first = compute(settings, resolve_plan(settings), quarter=all_["quarters"][0])
    assert first["quarter"] == all_["quarters"][0]
    windowed = compute(settings, resolve_plan(settings), start="2025-04", end="2025-09")
    assert windowed["quarters"] == ["2025-Q2", "2025-Q3"]
    with pytest.raises(IncentiveError, match="not available"):
        compute(settings, resolve_plan(settings), quarter="2019-Q1")


def test_incentive_needs_prior_year(settings):
    with pytest.raises(IncentiveError, match="prior-year"):
        compute(settings, resolve_plan(settings), start="2024-01", end="2024-12")


def test_plan_what_ifs_move_cost_the_right_way(settings):
    cost = lambda **o: compute(settings, resolve_plan(settings, o))["summary"]["total_payout"]
    assert cost(quota_growth_pct=15) < cost(quota_growth_pct=0)           # harder quotas pay less
    assert cost(accelerator=3.0) > cost(accelerator=0.0)                  # steeper accelerator pays more
    assert cost(target_incentive=24000) == pytest.approx(2 * cost(target_incentive=12000), rel=1e-6)


def test_incentive_without_territories(scratch_settings, tmp_path):
    hcp, act, rx = generate(scratch_settings.simulation)
    hcp.drop(columns=["territory_id"]).to_csv(tmp_path / "hcp.csv", index=False)
    act.to_csv(tmp_path / "activity.csv", index=False)
    rx.to_csv(tmp_path / "rx.csv", index=False)
    import_csv_dir(scratch_settings, tmp_path)
    with pytest.raises(IncentiveError, match="territory"):
        compute(scratch_settings, resolve_plan(scratch_settings))


def test_import_with_territories_and_validation(scratch_settings, tmp_path):
    sim = scratch_settings.simulation
    hcp, act, rx = generate(sim)
    hcp.to_csv(tmp_path / "hcp.csv", index=False)
    act.to_csv(tmp_path / "activity.csv", index=False)
    rx.to_csv(tmp_path / "rx.csv", index=False)
    with pytest.raises(ImportError_, match="territory.csv is missing"):
        import_csv_dir(scratch_settings, tmp_path)
    make_territories(sim).to_csv(tmp_path / "territory.csv", index=False)
    res = import_csv_dir(scratch_settings, tmp_path)
    assert res["territories"] == len(make_territories(sim))
    pd.DataFrame({"territory_id": [1], "name": ["x"], "region": ["West"], "rep_name": ["r"]}).to_csv(tmp_path / "territory.csv", index=False)
    with pytest.raises(ImportError_, match="not in territory.csv"):
        import_csv_dir(scratch_settings, tmp_path)


# ---------- targeting ----------
def test_targeting_deciles_and_shares(settings):
    res = service.get_targeting(settings, an.Filters())
    d = res["deciles"]
    assert len(d) == settings.targeting["deciles"] and sum(r["hcps"] for r in d) == 600
    assert sum(r["rx_share_pct"] for r in d) == pytest.approx(100, abs=0.6)
    assert sum(r["call_share_pct"] for r in d) == pytest.approx(100, abs=0.6)
    assert [r["trx"] for r in d] == sorted((r["trx"] for r in d), reverse=True)     # decile 1 = biggest prescribers
    t = settings.targeting
    for r in d:
        want = "Over-served" if r["call_index"] > t["over_index"] else "Under-served" if r["call_index"] < t["under_index"] else "Balanced"
        assert r["action"].startswith(want)
    assert sum(s["hcps"] for s in res["segments"]) == 600
    assert 0 < res["summary"]["alignment_score_pct"] <= 100


def test_targeting_misaligned_lists(settings):
    res = service.get_targeting(settings, an.Filters())
    hv = settings.targeting["high_volume_deciles"]
    assert all(r["decile"] <= hv and r["calls"] < res["median_calls_high_volume"] for r in res["under_served"])
    assert all(r["decile"] > hv and r["calls"] >= res["median_calls_high_volume"] for r in res["over_served"])
    assert len(res["under_served"]) <= settings.targeting["misaligned_top"]


def test_targeting_perfect_alignment_scores_100():
    totals = pd.DataFrame({"hcp_id": range(1, 11), "name": "x", "tier": "A", "region": "W", "specialty": "s",
                           "trx": [100] * 10, "calls": [5] * 10})
    cfg = {"deciles": 5, "over_index": 1.2, "under_index": 0.8, "high_volume_deciles": 2, "misaligned_top": 3}
    res = analyze(totals, cfg, None)
    assert res["summary"]["alignment_score_pct"] == 100.0 and res["segments"] is None
    assert all(r["action"] == "Balanced" for r in res["deciles"])


def test_targeting_handles_empty_and_tiny_inputs():
    cfg = {"deciles": 10, "over_index": 1.2, "under_index": 0.8, "high_volume_deciles": 3, "misaligned_top": 5}
    assert analyze(pd.DataFrame(columns=["hcp_id", "trx", "calls"]), cfg)["deciles"] == []
    tiny = pd.DataFrame({"hcp_id": [1, 2], "name": "x", "tier": "A", "region": "W", "specialty": "s", "trx": [10, 5], "calls": [0, 0]})
    res = analyze(tiny, cfg, None)
    assert res["summary"]["deciles"] == 2 and all(r["trx_per_call"] is None for r in res["deciles"])
