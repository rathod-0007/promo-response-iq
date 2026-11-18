"""Load real data from CSV files into the warehouse (replaces the synthetic data).

Expected files in the directory:
  hcp.csv       hcp_id, name, specialty, region, tier (A/B/C)
  activity.csv  hcp_id, month (YYYY-MM), calls, samples, emails
  rx.csv        hcp_id, month (YYYY-MM), trx
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import Settings
from .db import SQL_DIR, connect

REQUIRED = {
    "hcp": ["hcp_id", "name", "specialty", "region", "tier"],
    "activity": ["hcp_id", "month", "calls", "samples", "emails"],
    "rx": ["hcp_id", "month", "trx"],
}


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
    if df.duplicated([c for c in ("hcp_id", "month") if c in df.columns] or ["hcp_id"]).any():
        raise ImportError_(f"{path.name} contains duplicate keys")
    return df


def import_csv_dir(settings: Settings, folder: str | Path) -> dict:
    folder = Path(folder)
    hcp, act, rx = (_read(folder, n) for n in ("hcp", "activity", "rx"))
    if (set(act["hcp_id"]) | set(rx["hcp_id"])) - set(hcp["hcp_id"]):
        raise ImportError_("activity/rx reference HCP ids that are not in hcp.csv")
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings.db_path.with_suffix(".import.tmp")
    if tmp.exists():
        tmp.unlink()
    staged = Settings(db_path=tmp, simulation=settings.simulation, economics=settings.economics, model=settings.model)
    conn = connect(staged)
    try:
        with conn:
            conn.executescript((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
            hcp.to_sql("hcp", conn, if_exists="append", index=False)
            act.to_sql("activity", conn, if_exists="append", index=False, chunksize=5000)
            rx.to_sql("rx", conn, if_exists="append", index=False, chunksize=5000)
            conn.executescript((SQL_DIR / "views.sql").read_text(encoding="utf-8"))
    except Exception as e:  # constraint failures: leave the live DB untouched
        conn.close()
        tmp.unlink(missing_ok=True)
        raise ImportError_(f"Data failed validation: {e}") from e
    conn.close()
    tmp.replace(settings.db_path)
    return {"hcps": len(hcp), "activity_rows": len(act), "rx_rows": len(rx)}
