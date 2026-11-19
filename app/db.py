"""PostgreSQL warehouse: engine, schema creation, transactional (all-or-nothing) loading."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import Settings
from .datagen import generate

SQL_DIR = Path(__file__).resolve().parent / "sql"
_engines: dict[tuple[str, str], Engine] = {}


def get_engine(settings: Settings) -> Engine:
    key = (settings.database_url, settings.schema)
    if key not in _engines:
        _engines[key] = create_engine(
            settings.database_url, pool_pre_ping=True, pool_size=5, max_overflow=5,
            connect_args={"options": f"-csearch_path={settings.schema}"},
        )
    return _engines[key]


def dispose_engine(settings: Settings) -> None:
    eng = _engines.pop((settings.database_url, settings.schema), None)
    if eng is not None:
        eng.dispose()


def is_loaded(settings: Settings) -> bool:
    with get_engine(settings).connect() as conn:
        if conn.execute(text("SELECT to_regclass('hcp')")).scalar() is None:
            return False
        return conn.execute(text("SELECT COUNT(*) FROM hcp")).scalar() > 0


def data_version(settings: Settings) -> int:
    """Monotonic id of the last load; used to invalidate cached models."""
    with get_engine(settings).connect() as conn:
        return int(conn.execute(text("SELECT COALESCE(MAX(load_id), 0) FROM data_load")).scalar())


def load_frames(settings: Settings, hcp: pd.DataFrame, activity: pd.DataFrame, rx: pd.DataFrame,
                source: str) -> None:
    """Replace all data in ONE transaction: any failure leaves the previous data untouched."""
    schema_sql = (SQL_DIR / "schema.sql").read_text(encoding="utf-8")
    views_sql = (SQL_DIR / "views.sql").read_text(encoding="utf-8")
    with get_engine(settings).begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{settings.schema}"')
        conn.exec_driver_sql(schema_sql)
        conn.exec_driver_sql("TRUNCATE rx, activity, hcp")
        opts = dict(index=False, method="multi", chunksize=2000)
        hcp.to_sql("hcp", conn, if_exists="append", **opts)
        activity.to_sql("activity", conn, if_exists="append", **opts)
        rx.to_sql("rx", conn, if_exists="append", **opts)
        conn.exec_driver_sql(views_sql)
        conn.execute(text("INSERT INTO data_load (source) VALUES (:s)"), {"s": source})


def init_db(settings: Settings, reset: bool = False) -> None:
    if reset:
        with get_engine(settings).begin() as conn:
            conn.exec_driver_sql("DROP VIEW IF EXISTS v_region_summary, v_monthly_summary, v_hcp_month")
            conn.exec_driver_sql("DROP TABLE IF EXISTS rx, activity, hcp, data_load CASCADE")
    hcp, activity, rx = generate(settings.simulation)
    load_frames(settings, hcp, activity, rx, "synthetic")


def ensure_db(settings: Settings) -> None:
    if not is_loaded(settings):
        init_db(settings)
