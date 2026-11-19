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
