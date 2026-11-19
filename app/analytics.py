"""SQL-backed descriptive analytics. All filters are parameterised; dimensions are whitelisted."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import text

from .config import Settings
from .db import get_engine

DIMENSIONS = ("region", "specialty", "tier")


@dataclass(frozen=True)
class Filters:
    region: str | None = None
    specialty: str | None = None
    tier: str | None = None
    start: str | None = None  # YYYY-MM inclusive
    end: str | None = None    # YYYY-MM inclusive

    def key(self) -> tuple:
        return (self.region, self.specialty, self.tier, self.start, self.end)


def _where(f: Filters) -> tuple[str, dict]:
    clauses, params = [], {}
    for col in DIMENSIONS:
        val = getattr(f, col)
        if val:
            clauses.append(f"{col} = :{col}")
            params[col] = val
    if f.start:
        clauses.append("month >= :start")
        params["start"] = f.start
    if f.end:
        clauses.append("month <= :end")
        params["end"] = f.end
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _query(settings: Settings, sql: str, params=None) -> pd.DataFrame:
    with get_engine(settings).connect() as conn:
        return pd.read_sql_query(text(sql), conn, params=params or {})


def meta(settings: Settings) -> dict:
    out = {}
    for col in DIMENSIONS:
        df = _query(settings, f"SELECT DISTINCT {col} AS v FROM hcp ORDER BY v")
        out[col + "s" if col != "specialty" else "specialties"] = df["v"].tolist()
    rng = _query(settings, "SELECT MIN(month) AS lo, MAX(month) AS hi FROM v_hcp_month").iloc[0]
    out["min_month"], out["max_month"] = rng["lo"], rng["hi"]
    return out


def panel(settings: Settings, f: Filters) -> pd.DataFrame:
    where, params = _where(f)
    return _query(settings, "SELECT * FROM v_hcp_month" + where + " ORDER BY hcp_id, month", params)


def _pct_change(new: float, old: float):
    return None if not old else round((new - old) / old * 100, 2)


def kpis(settings: Settings, f: Filters) -> dict:
    where, params = _where(f)
    tot = _query(settings, "SELECT COALESCE(SUM(trx),0) AS trx, COALESCE(SUM(calls),0) AS calls, "
                 "COALESCE(SUM(samples),0) AS samples, COALESCE(SUM(emails),0) AS emails, "
                 "COUNT(DISTINCT hcp_id) AS hcps FROM v_hcp_month" + where, params).iloc[0]
    monthly = trend(settings, f)
    change = None
    if len(monthly) >= 12:
        last, prev = monthly.tail(6)["trx"].sum(), monthly.iloc[-12:-6]["trx"].sum()
        change = _pct_change(last, prev)
    trx, calls = int(tot["trx"]), int(tot["calls"])
    return {
        "total_trx": trx, "total_calls": calls, "total_samples": int(tot["samples"]),
        "total_emails": int(tot["emails"]), "active_hcps": int(tot["hcps"]),
        "trx_per_call": round(trx / calls, 3) if calls else None,
        "trx_change_pct_6m": change,
    }


def trend(settings: Settings, f: Filters) -> pd.DataFrame:
    where, params = _where(f)
    return _query(settings, "SELECT month, SUM(trx) AS trx, SUM(calls) AS calls, SUM(samples) AS samples, "
                  "SUM(emails) AS emails FROM v_hcp_month" + where + " GROUP BY month ORDER BY month", params)


def breakdown(settings: Settings, f: Filters, by: str) -> pd.DataFrame:
    if by not in DIMENSIONS:
        raise ValueError(f"unsupported dimension: {by}")
    where, params = _where(f)
    df = _query(settings, f"SELECT {by} AS name, SUM(trx) AS trx, SUM(calls) AS calls, "
                f"COUNT(DISTINCT hcp_id) AS hcps FROM v_hcp_month{where} GROUP BY {by} ORDER BY trx DESC, name", params)
    df["trx_per_call"] = (df["trx"] / df["calls"].where(df["calls"] > 0)).round(3)
    return df


def top_hcps(settings: Settings, f: Filters, limit: int = 15) -> pd.DataFrame:
    where, params = _where(f)
    return _query(settings,
                  "SELECT t.hcp_id, h.name, t.specialty, t.region, t.tier, t.trx, t.calls FROM "
                  "(SELECT hcp_id, specialty, region, tier, SUM(trx) AS trx, SUM(calls) AS calls "
                  "FROM v_hcp_month" + where + " GROUP BY hcp_id, specialty, region, tier) t "
                  "JOIN hcp h ON h.hcp_id = t.hcp_id ORDER BY t.trx DESC, t.hcp_id LIMIT :lim",
                  {**params, "lim": int(limit)})
