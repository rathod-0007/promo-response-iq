"""Dataset profile: the names, channels, economics and column mapping of whatever data is loaded.

The profile is stored with every warehouse load (data_load.profile) so that every page, insight and
export speaks the language of the uploaded file (e.g. "NBRx", "Detail visits", "Prescribers").
"""
from __future__ import annotations

import copy

from sqlalchemy import text

from .config import Settings
from .db import data_version, get_engine, has_territories

CHANNEL_ORDER = ("calls", "samples", "emails")
DIM_KEYS = ("region", "specialty", "tier")
_cache: dict = {}


def default_profile(settings: Settings) -> dict:
    """Profile of the built-in synthetic data set."""
    return {
        "name": "Synthetic demo data", "kind": "synthetic", "source_file": None,
        "labels": {"entity": "HCP", "entities": "HCPs", "metric": "Rx", "metric_long": "prescriptions",
                   "tier": "Tier", "region": "Region", "specialty": "Specialty", "territory": "Territory", "rep": "Rep"},
        "channels": [{"key": "calls", "label": "Calls", "unit": "call", "active": True},
                     {"key": "samples", "label": "Samples", "unit": "sample", "active": True},
                     {"key": "emails", "label": "E-mails", "unit": "e-mail", "active": True}],
        "economics": {}, "mapping": {}, "derived": [], "warnings": [],
    }


def _counts(settings: Settings) -> dict:
    with get_engine(settings).connect() as conn:
        row = conn.execute(text("SELECT COUNT(DISTINCT region) AS region, COUNT(DISTINCT specialty) AS specialty, "
                                "COUNT(DISTINCT tier) AS tier FROM hcp")).mappings().one()
    return dict(row)


def get_profile(settings: Settings) -> dict:
    """Profile of the data currently loaded (cached per load)."""
    key = (settings.database_url, settings.schema, data_version(settings))
    if key in _cache:
        return _cache[key]
    with get_engine(settings).connect() as conn:
        row = conn.execute(text("SELECT source, profile FROM data_load ORDER BY load_id DESC LIMIT 1")).mappings().first()
    prof = copy.deepcopy(row["profile"]) if row and row["profile"] else default_profile(settings)
    counts = _counts(settings)
    prof["dimensions"] = [{"key": k, "label": prof["labels"].get(k, k.title()), "values": int(counts[k]), "active": counts[k] > 1}
                          for k in DIM_KEYS]
    prof["has_territories"] = has_territories(settings)
    prof["source"] = row["source"] if row else "none"
    if len(_cache) > 16:
        _cache.clear()
    _cache[key] = prof
    return prof


def effective_economics(settings: Settings, profile: dict | None = None) -> dict:
    """Config economics, overridden by anything the uploader supplied for this data set."""
    profile = profile or get_profile(settings)
    return {**settings.economics, **profile.get("economics", {})}


def channel(profile: dict, key: str) -> dict:
    return next(c for c in profile["channels"] if c["key"] == key)


def active_channels(profile: dict) -> list[str]:
    return [c["key"] for c in profile["channels"] if c["active"]]


def tokens(profile: dict) -> dict:
    """Flat label dictionary used by server-side text (insights, exports, advice)."""
    lb, ch = profile["labels"], {c["key"]: c for c in profile["channels"]}
    first = ch["calls"]
    return {
        "entity": lb["entity"], "entities": lb["entities"], "entities_l": lb["entities"].lower(), "metric": lb["metric"], "metric_long": lb.get("metric_long", lb["metric"]),
        "primary": first["label"], "primary_l": first["label"].lower(), "primary_unit": first["unit"],
        "second": ch["samples"]["label"], "second_l": ch["samples"]["label"].lower(), "second_unit": ch["samples"]["unit"],
        "third": ch["emails"]["label"], "third_l": ch["emails"]["label"].lower(), "third_unit": ch["emails"]["unit"],
        "region": lb["region"], "specialty": lb["specialty"], "tier": lb["tier"], "territory": lb["territory"], "rep": lb["rep"],
    }


def channel_label(profile: dict, key: str) -> str:
    return channel(profile, key)["label"]


def tier_name(profile: dict, value: str) -> str:
    """'A' -> 'Tier A' (short codes get the tier label); descriptive values such as 'Platinum' stay as they are."""
    return f"{profile['labels']['tier']} {value}" if len(str(value)) <= 2 else str(value)
