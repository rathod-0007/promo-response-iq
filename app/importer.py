"""Load real data from CSV files into PostgreSQL (replaces the current data atomically).

Files in the directory:
  hcp.csv        hcp_id, name, specialty, region, tier (A/B/C)  [+ optional territory_id]
  activity.csv   hcp_id, month (YYYY-MM), calls, samples, emails
  rx.csv         hcp_id, month (YYYY-MM), trx
  territory.csv  OPTIONAL: territory_id, name, region, rep_name (needed for the incentive-compensation page)
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
    "territory": ["territory_id", "name", "region", "rep_name"],
}
KEYS = {"hcp": ["hcp_id"], "activity": ["hcp_id", "month"], "rx": ["hcp_id", "month"], "territory": ["territory_id"]}


class ImportError_(ValueError):
    pass


def _read(folder: Path, name: str, optional_cols: tuple = ()) -> pd.DataFrame:
    path = folder / f"{name}.csv"
    if not path.exists():
        raise ImportError_(f"Missing file: {path.name}")
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED[name] if c not in df.columns]
    if missing:
        raise ImportError_(f"{path.name} is missing columns: {', '.join(missing)}")
    keep = REQUIRED[name] + [c for c in optional_cols if c in df.columns]
    df = df[keep].dropna(subset=REQUIRED[name])
    if df.duplicated(KEYS[name]).any():
        raise ImportError_(f"{path.name} contains duplicate keys")
    return df


def import_csv_dir(settings: Settings, folder) -> dict:
    folder = Path(folder)
    hcp = _read(folder, "hcp", optional_cols=("territory_id",))
    act, rx = _read(folder, "activity"), _read(folder, "rx")
    territory = _read(folder, "territory") if (folder / "territory.csv").exists() else None
    if (set(act["hcp_id"]) | set(rx["hcp_id"])) - set(hcp["hcp_id"]):
        raise ImportError_("activity/rx reference HCP ids that are not in hcp.csv")
    if "territory_id" in hcp.columns:
        if territory is None:
            raise ImportError_("hcp.csv has territory_id but territory.csv is missing")
        hcp["territory_id"] = hcp["territory_id"].astype("Int64")
        if set(hcp["territory_id"].dropna()) - set(territory["territory_id"]):
            raise ImportError_("hcp.csv references territory ids that are not in territory.csv")
    try:
        load_frames(settings, hcp, act, rx, f"csv:{folder.name}", territory)
    except (SQLAlchemyError, PandasDatabaseError) as e:  # constraint/type failure: rolled back, old data intact
        cause = e.__cause__ or e
        detail = str(getattr(cause, "orig", cause)).splitlines()[0]
        raise ImportError_(f"Data failed validation: {detail}") from e
    return {"hcps": len(hcp), "activity_rows": len(act), "rx_rows": len(rx),
            "territories": 0 if territory is None else len(territory)}
