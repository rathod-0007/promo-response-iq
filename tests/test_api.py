import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pptx import Presentation

from app.main import create_app


@pytest.fixture(scope="module")
def client(settings):
    return TestClient(create_app(settings, frontend_dir="__missing__"))


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok", "database": "postgresql"}


def test_meta_is_dynamic(client, settings):
    m = client.get("/api/meta").json()
    assert m["regions"] == sorted(settings.simulation["regions"])
    assert m["min_month"] == settings.simulation["start_month"]
    assert m["economics"]["cost_per_call"] == settings.economics["cost_per_call"]


def test_kpis_and_filters(client):
    all_k = client.get("/api/kpis").json()
    west = client.get("/api/kpis", params={"region": "West"}).json()
    assert 0 < west["total_trx"] < all_k["total_trx"]


@pytest.mark.parametrize("params", [{"region": "Mars"}, {"tier": "Z"}, {"start": "2024/01"}, {"start": "2025-01", "end": "2024-01"}])
def test_bad_filters_rejected(client, params):
    assert client.get("/api/kpis", params=params).status_code == 422


def test_breakdown_unknown_dimension(client):
    assert client.get("/api/breakdown/name").status_code == 404
    assert len(client.get("/api/breakdown/tier").json()) == 3


def test_model_and_optimize(client):
    m = client.get("/api/model").json()
    assert set(m["model"]["tier_beta"]) == {"A", "B", "C"} and m["roi"]
    o = client.get("/api/optimize", params={"budget_change_pct": 10}).json()
    assert o["summary"]["recommended_calls"] > o["summary"]["current_calls"]
    assert len(o["top_moves"]) == 12
    assert client.get("/api/optimize", params={"budget_change_pct": 500}).status_code == 422


def test_model_with_too_little_data_returns_422(client):
    r = client.get("/api/model", params={"region": "West", "tier": "A", "start": "2024-01", "end": "2024-02"})
    assert r.status_code == 422 and "observations" in r.json()["detail"].lower()


def test_insights(client):
    ins = client.get("/api/insights").json()["insights"]
    assert len(ins) >= 4 and all(isinstance(s, str) for s in ins)


def test_excel_export(client):
    r = client.get("/api/export/xlsx", params={"region": "West"})
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    assert {"Summary", "Monthly Trend", "Response Model", "Channel ROI", "Calls Plan"} <= set(wb.sheetnames)
    assert wb["Calls Plan"].max_row > 10


def test_powerpoint_export(client):
    r = client.get("/api/export/pptx")
    assert r.status_code == 200
    deck = Presentation(io.BytesIO(r.content))
    assert len(deck.slides) == 6


def test_outage_handler_maps_operational_error(client):
    from sqlalchemy.exc import OperationalError
    from app import service

    original = service.get_model
    service.get_model = lambda *a, **k: (_ for _ in ()).throw(OperationalError("SELECT 1", {}, Exception("down")))
    try:
        r = client.get("/api/model")
    finally:
        service.get_model = original
    assert r.status_code == 503 and "unavailable" in r.json()["detail"].lower()


def test_hcp_list_pagination_and_sort(client):
    r1 = client.get("/api/hcps", params={"page_size": 10, "sort": "trx", "order": "desc"}).json()
    assert r1["total"] == 600 and len(r1["rows"]) == 10
    trx = [x["trx"] for x in r1["rows"]]
    assert trx == sorted(trx, reverse=True)
    r2 = client.get("/api/hcps", params={"page_size": 10, "page": 2}).json()
    assert {x["hcp_id"] for x in r1["rows"]}.isdisjoint({x["hcp_id"] for x in r2["rows"]})
    asc = client.get("/api/hcps", params={"sort": "name", "order": "asc"}).json()["rows"]
    assert [x["name"] for x in asc] == sorted(x["name"] for x in asc)


def test_hcp_list_search_and_filters(client):
    one = client.get("/api/hcps", params={"q": "HCP-0007"}).json()
    assert one["total"] == 1 and one["rows"][0]["name"] == "Dr. HCP-0007"
    partial = client.get("/api/hcps", params={"q": "hcp-006", "page_size": 100}).json()   # case-insensitive substring
    assert partial["total"] == 10 and all("HCP-006" in x["name"] for x in partial["rows"])
    west = client.get("/api/hcps", params={"region": "West", "page_size": 100}).json()
    assert 0 < west["total"] < 600 and {x["region"] for x in west["rows"]} == {"West"}


def test_hcp_list_is_safe_and_validated(client):
    assert client.get("/api/hcps", params={"q": "%"}).json()["total"] == 0          # literal %, not a wildcard
    assert client.get("/api/hcps", params={"q": "x'; DROP TABLE hcp; --"}).json()["total"] == 0
    assert client.get("/api/hcps").json()["total"] == 600                           # table intact
    assert client.get("/api/hcps", params={"sort": "name; DROP"}).status_code == 422
    assert client.get("/api/hcps", params={"order": "sideways"}).status_code == 422
    assert client.get("/api/hcps", params={"page": 0}).status_code == 422


def test_data_info(client, settings):
    d = client.get("/api/data-info").json()
    assert d["source"] == "synthetic" and d["hcps"] == settings.simulation["n_hcps"]
    assert d["first_month"] == settings.simulation["start_month"] and d["rx_rows"] == d["activity_rows"]


def test_meta_exposes_incentive_defaults(client, settings):
    m = client.get("/api/meta").json()
    assert m["has_territories"] is True and m["incentive"]["accelerator"] == settings.incentive["accelerator"]


def test_incentive_endpoint_and_overrides(client):
    base = client.get("/api/incentive").json()
    assert base["summary"]["territories"] == 24 and base["quarter"] == base["quarters"][-1]
    hard = client.get("/api/incentive", params={"quota_growth_pct": 20}).json()
    assert hard["summary"]["total_payout"] < base["summary"]["total_payout"]
    assert hard["plan"]["quota_growth_pct"] == 20
    west = client.get("/api/incentive", params={"region": "West", "quarter": base["quarters"][0]}).json()
    assert west["quarter"] == base["quarters"][0] and {t["region"] for t in west["territories"]} == {"West"}


def test_incentive_validation(client):
    assert client.get("/api/incentive", params={"quarter": "2025-Q9"}).status_code == 422
    assert client.get("/api/incentive", params={"accelerator": 50}).status_code == 422
    assert client.get("/api/incentive", params={"region": "Mars"}).status_code == 422
    r = client.get("/api/incentive", params={"start": "2024-01", "end": "2024-12"})
    assert r.status_code == 422 and "prior-year" in r.json()["detail"]
    assert client.get("/api/incentive", params={"quarter": "2019-Q1"}).status_code == 422


def test_incentive_ignores_specialty_and_tier_filters(client):
    a = client.get("/api/incentive").json()["summary"]
    b = client.get("/api/incentive", params={"specialty": "Cardiology", "tier": "A"}).json()["summary"]
    assert a == b


def test_targeting_endpoint(client):
    t = client.get("/api/targeting").json()
    assert len(t["deciles"]) == 10 and len(t["segments"]) == 4 and t["summary"]["hcps"] == 600
    west = client.get("/api/targeting", params={"region": "West"}).json()
    assert 0 < west["summary"]["hcps"] < 600
    assert client.get("/api/targeting", params={"tier": "Z"}).status_code == 422


def test_data_dictionary(client):
    d = {t["name"]: t for t in client.get("/api/data-dictionary").json()}
    assert {"hcp", "rx", "activity", "territory", "v_hcp_month", "v_territory_month"} <= set(d)
    assert d["hcp"]["kind"] == "table" and d["v_hcp_month"]["kind"] == "view"
    tier = next(c for c in d["hcp"]["columns"] if c["name"] == "tier")
    assert tier["type"] == "text" and "segment" in tier["description"]
    assert d["hcp"]["description"]


def test_insights_mention_targeting_and_incentives(client):
    text_ = " ".join(client.get("/api/insights").json()["insights"])
    assert "alignment score" in text_ and "territory-quarters reach quota" in text_


def test_excel_has_new_sheets(client):
    r = client.get("/api/export/xlsx")
    wb = load_workbook(io.BytesIO(r.content))
    assert {"Targeting Deciles", "Segments", "IC By Quarter"} <= set(wb.sheetnames)
    assert any(n.startswith("IC Territory") for n in wb.sheetnames)
