import io
import zipfile
from dataclasses import replace

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.main as main
from app import bi
from app.db import get_engine
from app.main import create_app
from test_upload import MAP, make_df


@pytest.fixture(scope="module")
def client(settings):
    return TestClient(create_app(settings, frontend_dir="__missing__"))


# ---------- BI star schema and analysis tables ----------
def test_star_schema_views_reconcile(settings):
    with get_engine(settings).connect() as c:
        fact = c.execute(text("SELECT SUM(trx), SUM(calls), COUNT(*) FROM bi_fact_hcp_month")).one()
        base = c.execute(text("SELECT SUM(trx), (SELECT SUM(calls) FROM activity), (SELECT COUNT(*) FROM rx) FROM rx")).one()
        assert tuple(fact) == tuple(base)
        joined = c.execute(text("SELECT SUM(f.trx) FROM bi_fact_hcp_month f JOIN bi_dim_hcp h USING (hcp_id) JOIN bi_dim_month m USING (month_start)")).scalar()
        assert joined == fact[0]                                   # every fact row finds its dimension rows
        months = c.execute(text("SELECT month_start, month_key, year, quarter, quarter_label, month_name FROM bi_dim_month ORDER BY month_start")).all()
    assert len(months) == settings.simulation["n_months"]
    assert str(months[0][0]) == f"{settings.simulation['start_month']}-01" and months[0][4] == "2024-Q1" and months[0][5] == "Jan"


def test_bi_info_lists_objects_with_comments(client):
    info = client.get("/api/bi/info").json()
    names = {o["name"]: o for o in info["objects"]}
    assert {"bi_fact_hcp_month", "bi_dim_hcp", "bi_dim_territory", "bi_dim_month"} <= set(names)
    assert set(bi.TABLES) <= set(names)                         # analysis tables were published at start-up
    assert all(o["description"] and o["rows"] > 0 and o["columns"] for o in names.values())
    assert names["bi_fact_hcp_month"]["kind"] == "view" and names["bi_model_terms"]["kind"] == "table"
    assert info["connection"]["driver"] == "postgresql" and "password" not in str(info).lower()
    assert info["refreshed_at"]


def test_published_tables_match_the_api(client, settings):
    opt = client.get("/api/optimize").json()["summary"]
    model = client.get("/api/model").json()["model"]
    with get_engine(settings).connect() as c:
        planned = c.execute(text("SELECT SUM(recommended_calls) FROM bi_call_plan")).scalar()
        terms = c.execute(text("SELECT COUNT(*) FROM bi_model_terms")).scalar()
        shares = c.execute(text("SELECT SUM(trx_share_pct), SUM(call_share_pct) FROM bi_targeting_deciles")).one()
        segments = c.execute(text("SELECT segment, COUNT(*) FROM bi_hcp_segment GROUP BY segment")).all()
    assert planned == opt["recommended_calls"] and terms == len(model["terms"])
    assert shares[0] == pytest.approx(100, abs=1) and shares[1] == pytest.approx(100, abs=1)
    assert {s[0] for s in segments} == {"Invest", "Defend", "Develop", "Self-serve"} and sum(s[1] for s in segments) == 600


def test_refresh_endpoint_republishes(client):
    r = client.post("/api/bi/refresh").json()
    assert set(r["published"]) == set(bi.TABLES) and r["published"]["bi_hcp_segment"] == 600 and r["published"]["bi_ic_territory_quarter"] > 0


def test_csv_pack(client):
    r = client.get("/api/export/bi")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"README.txt", "bi_fact_hcp_month.csv", "bi_dim_hcp.csv", "bi_model_terms.csv"} <= names
    fact = pd.read_csv(z.open("bi_fact_hcp_month.csv"))
    assert list(fact.columns) == ["hcp_id", "month_start", "month_key", "trx", "calls", "samples", "emails"] and len(fact) == 600 * 24
    assert "bi_fact_hcp_month.csv" in z.read("README.txt").decode()


def test_bi_tables_follow_the_loaded_dataset(scratch_settings, tmp_path):
    s = replace(scratch_settings, upload={**scratch_settings.upload, "dir": str(tmp_path / "up")})
    c = TestClient(create_app(s, frontend_dir="__missing__"))
    objects = lambda: {o["name"] for o in c.get("/api/bi/info").json()["objects"]}
    assert "bi_model_terms" not in objects()                       # 30 prescribers x 6 months is too little to model

    def upload(df, mapping, options=None):
        up = c.post("/api/upload/inspect", files={"file": ("x.csv", df.to_csv(index=False).encode(), "text/csv")}).json()
        return c.post("/api/upload/import", json={"upload_id": up["upload_id"], "mapping": mapping, "options": options or {}})

    with_terr = make_df(n=40, with_territory=True)
    assert upload(with_terr, {**MAP, "territory": "Terr"}, {"labels": {"metric": "NBRx"}}).status_code == 200
    assert {"bi_model_terms", "bi_ic_territory_quarter", "bi_ic_payout_curve"} <= objects()

    assert upload(make_df(n=40), MAP).status_code == 200            # a data set without territories
    info = c.get("/api/bi/info").json()
    names = {o["name"] for o in info["objects"]}
    assert "bi_ic_territory_quarter" not in names and "bi_model_terms" in names     # stale results are removed
    assert any("territory" in n.lower() for n in info["notes"])
    with get_engine(s).connect() as conn:
        labels = dict(conn.execute(text("SELECT label_key, label_value FROM bi_dataset_labels")).all())
    assert labels["label_metric"] == "Scripts" and labels["dataset_kind"] == "upload"      # metric label defaults to the mapped header


# ---------- server wiring ----------
def test_index_hint_when_frontend_is_not_built(client):
    r = client.get("/")
    assert r.status_code == 200 and "npm run dev" in r.text
    assert client.get("/api/health").status_code == 200


def test_built_frontend_is_served_with_cache_rules(settings, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>RxLift</title><script type=module src=/assets/app.js></script>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    c = TestClient(create_app(settings, frontend_dir=tmp_path))
    index = c.get("/")
    assert index.status_code == 200 and "RxLift" in index.text and index.headers["cache-control"] == "no-cache"
    asset = c.get("/assets/app.js")
    assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
    assert c.get("/api/health").json()["status"] == "ok"            # API routes win over the static mount


def test_cors_allows_only_configured_origins(settings):
    c = TestClient(create_app(settings, frontend_dir="__missing__"))
    ok = c.options("/api/kpis", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = c.options("/api/kpis", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


def test_cors_origins_can_be_set_by_environment(settings, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://bi.example.com, https://ui.example.com")
    c = TestClient(create_app(settings, frontend_dir="__missing__"))
    r = c.options("/api/kpis", headers={"Origin": "https://ui.example.com", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "https://ui.example.com"


def test_lazy_app_builds_once_and_has_no_import_side_effects(monkeypatch):
    assert isinstance(main.app, main.LazyApp) and main.app._app is None            # importing the module touched nothing
    built = []

    async def fake(scope, receive, send):
        built.append(scope["type"])

    monkeypatch.setattr(main, "create_app", lambda *a, **k: fake)
    lazy = main.LazyApp()
    import asyncio
    asyncio.run(lazy({"type": "http"}, None, None))
    asyncio.run(lazy({"type": "http"}, None, None))
    assert built == ["http", "http"] and lazy._app is fake
