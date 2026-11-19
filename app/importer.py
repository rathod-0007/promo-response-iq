"""Load real data from CSV files into PostgreSQL (replaces the current data atomically).

Expected files in the directory:
  hcp.csv       hcp_id, name, specialty, region, tier (A/B/C)
  activity.csv  hcp_id, month (YYYY-MM), calls, samples, emails
  rx.csv        hcp_id, month (YYYY-MM), trx
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from pandas.errors import DatabaseError as PandasDatabaseError
from sqlalchemy.exc import SQLAlchemyError

from .config import Settings
from .db import load_frames

REQUIRED = {
    "hcp": ["hcp_id", "name", "specialty", "region", "tier"],
    "activity": ["hcp_id", "month", "calls", "samples", "emails"],
    "rx": ["hcp_id", "month", "trx"],
}
KEYS = {"hcp": ["hcp_id"], "activity": ["hcp_id", "month"], "rx": ["hcp_id", "month"]}


class ImportError_(ValueError):
    pass


def _read(folder: Path, name: str) -> pd.DataFrame:
    path = folder / f"{name}.csv"
    if not path.exists():
        raise ImportError_(f"Missing file: {path.name}")
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED[name] if c not in df.columns]
    if missing:
        raise ImportError_(f"{path.name} is missing columns: {', '.join(missing)}")
    df = df[REQUIRED[name]].dropna()
    if df.duplicated(KEYS[name]).any():
        raise ImportError_(f"{path.name} contains duplicate keys")
    return df


def import_csv_dir(settings: Settings, folder) -> dict:
    folder = Path(folder)
    hcp, act, rx = (_read(folder, n) for n in ("hcp", "activity", "rx"))
    if (set(act["hcp_id"]) | set(rx["hcp_id"])) - set(hcp["hcp_id"]):
        raise ImportError_("activity/rx reference HCP ids that are not in hcp.csv")
    try:
        load_frames(settings, hcp, act, rx, f"csv:{folder.name}")
    except (SQLAlchemyError, PandasDatabaseError) as e:  # constraint/type failure: rolled back, old data intact
        cause = e.__cause__ or e
        detail = str(getattr(cause, "orig", cause)).splitlines()[0]
        raise ImportError_(f"Data failed validation: {detail}") from e
    return {"hcps": len(hcp), "activity_rows": len(act), "rx_rows": len(rx)}
