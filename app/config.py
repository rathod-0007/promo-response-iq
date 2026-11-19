"""Settings from config.json. Override with env: PROMO_CONFIG, DATABASE_URL, DB_SCHEMA."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


@dataclass(frozen=True)
class Settings:
    database_url: str
    schema: str
    simulation: dict
    economics: dict
    model: dict
    incentive: dict
    targeting: dict
    upload: dict
    server: dict

    def __post_init__(self):
        if not _IDENT.match(self.schema):
            raise ValueError(f"Invalid schema name: {self.schema!r}")


def load_settings(path=None, database_url=None, schema=None) -> Settings:
    cfg_path = Path(path or os.environ.get("PROMO_CONFIG") or ROOT / "config.json")
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    return Settings(
        database_url=database_url or os.environ.get("DATABASE_URL") or raw["database_url"],
        schema=schema or os.environ.get("DB_SCHEMA") or raw.get("schema", "public"),
        simulation=raw["simulation"], economics=raw["economics"], model=raw["model"],
        incentive=raw["incentive"], targeting=raw["targeting"], upload=raw["upload"],
        server=raw.get("server", {"cors_origins": [], "frontend_dist": "frontend/dist"}),
    )
