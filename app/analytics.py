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


HCP_SORTS = {"name": "name", "specialty": "specialty", "region": "region", "tier": "tier",
             "trx": "trx", "calls": "calls", "samples": "samples", "emails": "emails",
             "trx_per_call": "trx_per_call"}


def _like(q: str) -> str:
    """Escape LIKE wildcards so user input is matched literally (escape char is a backslash)."""
    bs = chr(92)
    return "%" + q.replace(bs, bs + bs).replace("%", bs + "%").replace("_", bs + "_") + "%"


def hcp_list(settings: Settings, f: Filters, q: str = "", sort: str = "trx", order: str = "desc",
             page: int = 1, page_size: int = 15) -> dict:
    """Server-side search / sort / pagination over HCP totals for the filtered window."""
    if sort not in HCP_SORTS:
        raise ValueError(f"unsupported sort: {sort}")
    if order not in ("asc", "desc"):
        raise ValueError("order must be asc or desc")
    where, params = _where(f)
    q = (q or "").strip()[:100]
    cte = (
        "WITH t AS (SELECT hcp_id, specialty, region, tier, SUM(trx) AS trx, SUM(calls) AS calls, "
        "SUM(samples) AS samples, SUM(emails) AS emails FROM v_hcp_month" + where +
        " GROUP BY hcp_id, specialty, region, tier), "
        "r AS (SELECT t.hcp_id, h.name, t.specialty, t.region, t.tier, t.trx, t.calls, t.samples, t.emails, "
        "ROUND(t.trx::numeric / NULLIF(t.calls, 0), 2)::float8 AS trx_per_call "
        "FROM t JOIN hcp h ON h.hcp_id = t.hcp_id "
        "WHERE (:q = '' OR h.name ILIKE :like ESCAPE '\\' OR t.hcp_id::text = :q)) "
    )
    base = {**params, "q": q, "like": _like(q)}
    total = int(_query(settings, cte + "SELECT COUNT(*) AS n FROM r", base).iloc[0]["n"])
    off = (max(page, 1) - 1) * page_size
    rows = _query(settings, cte + f"SELECT * FROM r ORDER BY {HCP_SORTS[sort]} {order.upper()} NULLS LAST, hcp_id "
                  "LIMIT :lim OFFSET :off", {**base, "lim": int(page_size), "off": int(off)})
    return {"total": total, "page": max(page, 1), "page_size": page_size, "rows": rows}


def data_info(settings: Settings) -> dict:
    last = _query(settings, "SELECT source, loaded_at FROM data_load ORDER BY load_id DESC LIMIT 1").iloc[0]
    cnt = _query(settings, "SELECT (SELECT COUNT(*) FROM hcp) AS hcps, (SELECT COUNT(*) FROM activity) AS activity_rows, "
                 "(SELECT COUNT(*) FROM rx) AS rx_rows, (SELECT MIN(month::text) FROM rx) AS first_month, "
                 "(SELECT MAX(month::text) FROM rx) AS last_month, (SELECT COUNT(*) FROM data_load) AS loads").iloc[0]
    hist = _query(settings, "SELECT load_id, source, loaded_at, profile->>'name' AS name, profile->'summary' AS summary "
                  "FROM data_load ORDER BY load_id DESC LIMIT 10")
    history = [{"load_id": int(r.load_id), "source": r.source, "loaded_at": r.loaded_at.isoformat(),
                "name": r.name if isinstance(r.name, str) else "Synthetic demo data",
                "summary": r.summary if isinstance(r.summary, dict) else None} for r in hist.itertuples()]
    return {"history": history, "source": str(last["source"]), "loaded_at": last["loaded_at"].isoformat(),
            "hcps": int(cnt["hcps"]), "activity_rows": int(cnt["activity_rows"]), "rx_rows": int(cnt["rx_rows"]),
            "first_month": cnt["first_month"], "last_month": cnt["last_month"], "loads": int(cnt["loads"]),
            "schema": settings.schema}


def hcp_totals(settings: Settings, f: Filters) -> pd.DataFrame:
    """One row per HCP for the filtered window (used by targeting analysis)."""
    where, params = _where(f)
    return _query(settings,
                  "SELECT t.hcp_id, h.name, t.tier, t.region, t.specialty, t.trx, t.calls FROM "
                  "(SELECT hcp_id, specialty, region, tier, SUM(trx) AS trx, SUM(calls) AS calls "
                  "FROM v_hcp_month" + where + " GROUP BY hcp_id, specialty, region, tier) t "
                  "JOIN hcp h ON h.hcp_id = t.hcp_id ORDER BY t.hcp_id", params)


def data_dictionary(settings: Settings) -> list[dict]:
    """Tables and views of the warehouse with column types and the comments defined in schema.sql."""
    df = _query(settings, """
        SELECT t.table_name, t.table_type, c.column_name, c.data_type, c.ordinal_position,
               obj_description(cl.oid, 'pg_class') AS table_comment,
               col_description(cl.oid, c.ordinal_position::int) AS column_comment
        FROM information_schema.tables t
        JOIN information_schema.columns c ON c.table_schema = t.table_schema AND c.table_name = t.table_name
        JOIN pg_class cl ON cl.relname = t.table_name
        JOIN pg_namespace n ON n.oid = cl.relnamespace AND n.nspname = t.table_schema
        WHERE t.table_schema = :schema
        ORDER BY t.table_type, t.table_name, c.ordinal_position""", {"schema": settings.schema})
    out = []
    for name, g in df.groupby("table_name", sort=False):
        first = g.iloc[0]
        out.append({"name": name, "kind": "view" if first["table_type"] == "VIEW" else "table",
                    "description": first["table_comment"] if isinstance(first["table_comment"], str) else "",
                    "columns": [{"name": r.column_name, "type": r.data_type,
                                 "description": r.column_comment if isinstance(r.column_comment, str) else ""}
                                for r in g.itertuples()]})
    return out


def hcp_names(settings: Settings) -> pd.Series:
    """hcp_id -> display name."""
    df = _query(settings, "SELECT hcp_id, name FROM hcp")
    return df.set_index("hcp_id")["name"]
