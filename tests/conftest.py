"""Tests run against a real PostgreSQL. Set TEST_DATABASE_URL (default: DATABASE_URL / config.json).

Every test session works in its own throw-away schema, dropped afterwards, so no data is touched.
"""
import copy
import json
import os
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ROOT, Settings  # noqa: E402
from app.db import dispose_engine, get_engine, init_db  # noqa: E402

RAW = json.loads((ROOT / "config.json").read_text())
URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or RAW["database_url"]


def make_settings(schema: str, **sim_overrides) -> Settings:
    sim = copy.deepcopy(RAW["simulation"])
    sim.update(sim_overrides)
    return Settings(database_url=URL, schema=schema, simulation=sim, economics=RAW["economics"], model=RAW["model"])


def drop_schema(s: Settings) -> None:
    with get_engine(Settings(URL, "public", s.simulation, s.economics, s.model)).begin() as conn:
        conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{s.schema}" CASCADE')
    dispose_engine(s)


@pytest.fixture(scope="session")
def settings():
    s = make_settings("t_" + uuid.uuid4().hex[:10])
    try:
        init_db(s)
    except Exception as e:  # pragma: no cover
        pytest.exit(f"PostgreSQL not reachable at TEST_DATABASE_URL/DATABASE_URL: {e}", returncode=2)
    yield s
    drop_schema(s)


@pytest.fixture()
def scratch_settings():
    """A brand-new empty schema per test (for importer tests)."""
    s = make_settings("t_" + uuid.uuid4().hex[:10], n_hcps=30, n_months=6)
    yield s
    drop_schema(s)


@pytest.fixture()
def sql(settings):
    def run(statement: str, **params):
        with get_engine(settings).begin() as conn:
            res = conn.execute(text(statement), params)
            return res.fetchall() if res.returns_rows else None
    return run
