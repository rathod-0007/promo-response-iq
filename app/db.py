"""SQLite warehouse: create schema, load data, open connections."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import Settings
from .datagen import generate

SQL_DIR = Path(__file__).resolve().parent / "sql"


def connect(settings: Settings) -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(settings: Settings, reset: bool = False) -> None:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    if reset and settings.db_path.exists():
        settings.db_path.unlink()
    hcp, activity, rx = generate(settings.simulation)
    conn = connect(settings)
    try:
        with conn:
            conn.executescript((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
            hcp.to_sql("hcp", conn, if_exists="append", index=False)
            activity.to_sql("activity", conn, if_exists="append", index=False, chunksize=5000)
            rx.to_sql("rx", conn, if_exists="append", index=False, chunksize=5000)
            conn.executescript((SQL_DIR / "views.sql").read_text(encoding="utf-8"))
    finally:
        conn.close()


def ensure_db(settings: Settings) -> None:
    if not settings.db_path.exists():
        init_db(settings)
