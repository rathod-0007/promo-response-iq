"""The generated Tableau workbook and Power BI project: structure, consistency with the data, and the download endpoints."""
import io
import json
import re
import sys
import zipfile
from dataclasses import replace
from xml.etree import ElementTree

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import bi, bi_powerbi
from app.main import create_app
from test_upload import MAP, make_df


@pytest.fixture(scope="module")
def client(settings):
    return TestClient(create_app(settings, frontend_dir="__missing__"))


def read_zip(content: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(content))


def tmdl_objects(z: zipfile.ZipFile) -> tuple[dict[str, set], dict[str, set]]:
    """table -> columns, table -> measures, read back from the generated TMDL files."""
    cols, measures = {}, {}
    for n in z.namelist():
        m = re.search(r"definition/tables/(.+)\.tmdl$", n)
        if m:
            text = z.read(n).decode()
            cols[m.group(1)] = set(re.findall(r"^\tcolumn '?([^'\n]+?)'?\s*$", text, re.M))
            measures[m.group(1)] = set(re.findall(r"^\tmeasure '?(.+?)'? = ", text, re.M))
    return cols, measures


# ---------- Power BI ----------
def test_powerbi_download_is_a_complete_project(client):
    r = client.get("/api/export/powerbi")
    assert r.status_code == 200 and "powerbi" in r.headers["content-disposition"]
    z = read_zip(r.content)
    names = set(z.namelist())
    assert {"README.txt", "PromoResponseIQ.pbip", "PromoResponseIQ.SemanticModel/definition/relationships.tmdl",
            "PromoResponseIQ.SemanticModel/definition/expressions.tmdl", "PromoResponseIQ.Report/definition/report.json"} <= names
    assert any(n.startswith("Data/bi_fact_hcp_month") for n in names)
    assert "C:\\PromoResponseIQ\\Data\\" in z.read("PromoResponseIQ.SemanticModel/definition/expressions.tmdl").decode()
    z2 = read_zip(client.get("/api/export/powerbi", params={"data_folder": "D:\\bi\\data"}).content)
    assert 'DataFolder = "D:\\bi\\data\\"' in z2.read("PromoResponseIQ.SemanticModel/definition/expressions.tmdl").decode()


def test_every_report_field_exists_in_the_model(client):
    z = read_zip(client.get("/api/export/powerbi").content)
    cols, measures = tmdl_objects(z)
    assert "bi_fact_hcp_month" in cols and measures["bi_fact_hcp_month"]
    visuals = [n for n in z.namelist() if n.endswith("visual.json")]
    assert len(visuals) >= 10
    for n in visuals:
        v = json.loads(z.read(n))
        for role in v["visual"]["query"]["queryState"].values():
            for p in role["projections"]:
                f = p["field"]
                node = f.get("Column") or f.get("Measure") or f["Aggregation"]["Expression"]["Column"]
                entity, prop = node["Expression"]["SourceRef"]["Entity"], node["Property"]
                pool = measures[entity] if "Measure" in f else cols[entity]
                assert prop in pool, f"{n}: {entity}.{prop} is not in the model"
    pages = json.loads(z.read("PromoResponseIQ.Report/definition/pages/pages.json"))["pageOrder"]
    assert len(pages) == 3


def test_relationships_point_many_to_one_at_dimension_keys(client):
    z = read_zip(client.get("/api/export/powerbi").content)
    cols, _ = tmdl_objects(z)
    rel = z.read("PromoResponseIQ.SemanticModel/definition/relationships.tmdl").decode()
    pairs = re.findall(r"fromColumn: (\w+)\.(\w+)\r?\n\ttoColumn: (\w+)\.(\w+)", rel)
    assert ("bi_fact_hcp_month", "hcp_id", "bi_dim_hcp", "hcp_id") in pairs
    assert ("bi_fact_hcp_month", "month_start", "bi_dim_month", "month_start") in pairs
    for ft, fc, tt, tc in pairs:
        assert tt.startswith("bi_dim_") and fc == tc and fc in cols[ft] and tc in cols[tt]


def test_powerbi_names_follow_the_dataset_labels(scratch_settings, tmp_path):
    s = replace(scratch_settings, upload={**scratch_settings.upload, "dir": str(tmp_path / "up")})
    c = TestClient(create_app(s, frontend_dir="__missing__"))
    up = c.post("/api/upload/inspect", files={"file": ("x.csv", make_df(n=40, with_territory=True).to_csv(index=False).encode(), "text/csv")}).json()
    assert c.post("/api/upload/import", json={"upload_id": up["upload_id"], "mapping": {**MAP, "territory": "Terr"},
                                              "options": {"labels": {"metric": "NBRx"}}}).status_code == 200
    out = tmp_path / "pbi"
    r = bi_powerbi.generate(s, out)
    assert r["pages"] >= 2 and (out / "PromoResponseIQ.pbip").exists()
    fact = (out / "PromoResponseIQ.SemanticModel" / "definition" / "tables" / "bi_fact_hcp_month.tmdl").read_text()
    assert "measure 'Total NBRx'" in fact and "Total Rx" not in fact
    titles = " ".join(p.read_text() for p in (out / "PromoResponseIQ.Report").rglob("visual.json"))
    assert "NBRx by month" in titles


def test_powerbi_singular_unit_in_ratio_measure(client):
    z = read_zip(client.get("/api/export/powerbi").content)
    _, measures = tmdl_objects(z)
    assert any(re.search(r" per [a-z ]+$", m) and not m.endswith("s") for m in measures["bi_fact_hcp_month"])


# ---------- Tableau ----------
def test_tableau_download_has_workbook_and_matching_extracts(client):
    pytest.importorskip("tableauhyperapi")
    from tableauhyperapi import Connection, HyperProcess, Telemetry
    r = client.get("/api/export/tableau")
    assert r.status_code == 200 and "twbx" in r.headers["content-disposition"]
    z = read_zip(r.content)
    names = z.namelist()
    assert "PromoResponseIQ.twb" in names
    hypers = [n for n in names if n.endswith(".hyper")]
    assert "Data/Extracts/bi_flat_hcp_month.hyper" in hypers
    root = ElementTree.fromstring(z.read("PromoResponseIQ.twb"))
    sheets = [w.get("name") for w in root.iter("worksheet")]
    assert len(sheets) >= 6 and len(sheets) == len(set(sheets))
    dash = [d.get("name") for d in root.iter("dashboard")]
    assert dash and all(zn.get("name") in sheets for d in root.iter("dashboard") for zn in d.iter("zone") if zn.get("name"))
    for ds in root.find("datasources"):
        assert re.match(r"^Data/Extracts/\w+\.hyper$", ds.find("connection/named-connections/named-connection/connection").get("dbname"))
    # extract row counts equal what the database holds
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp, HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp:
        p = Path(tmp) / "flat.hyper"
        p.write_bytes(z.read("Data/Extracts/bi_flat_hcp_month.hyper"))
        with Connection(hp.endpoint, str(p)) as conn:
            n = conn.execute_scalar_query('SELECT COUNT(*) FROM "Extract"."Extract"')
    assert n == 600 * 24


def test_tableau_export_says_what_to_install_when_the_package_is_missing(client, monkeypatch):
    import app
    monkeypatch.setitem(sys.modules, "tableauhyperapi", None)              # as if the optional package were not installed
    monkeypatch.delitem(sys.modules, "app.bi_tableau", raising=False)
    monkeypatch.delattr(app, "bi_tableau", raising=False)
    r = client.get("/api/export/tableau")
    assert r.status_code == 503 and "requirements-bi.txt" in r.json()["detail"]
