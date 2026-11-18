"""Settings loaded from config.json (override path with PROMO_CONFIG, DB with PROMO_DB)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    db_path: Path
    simulation: dict
    economics: dict
    model: dict


def load_settings(path=None, db_path=None) -> Settings:
    cfg_path = Path(path or os.environ.get("PROMO_CONFIG") or ROOT / "config.json")
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    db = Path(db_path or os.environ.get("PROMO_DB") or raw["database"])
    if not db.is_absolute():
        db = ROOT / db
    return Settings(db_path=db, simulation=raw["simulation"], economics=raw["economics"], model=raw["model"])
