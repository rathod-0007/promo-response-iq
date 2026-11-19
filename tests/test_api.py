import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pptx import Presentation

from app.main import create_app


@pytest.fixture(scope="module")
def client(settings):
    return TestClient(create_app(settings))


def test_health_and_index(client):
    assert client.get("/api/health").json() == {"status": "ok", "database": "postgresql"}
    r = client.get("/")
    assert r.status_code == 200 and "PromoResponseIQ" in r.text
    assert client.get("/static/app.js").status_code == 200


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
    assert {"Summary", "Monthly Trend", "Response Model", "Channel ROI", "Call Plan"} <= set(wb.sheetnames)
    assert wb["Call Plan"].max_row > 10


def test_powerpoint_export(client):
    r = client.get("/api/export/pptx")
    assert r.status_code == 200
    deck = Presentation(io.BytesIO(r.content))
    assert len(deck.slides) == 5


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
