"""Incentive-compensation (IC) analytics: quota attainment, payout curve and plan cost.

Quota rule: a territory's quarterly quota = its Rx in the same quarter of the prior year x (1 + growth).
Payout curve (all parameters come from config.json and can be overridden per request for what-ifs):
  attainment < threshold            -> 0
  threshold <= attainment < 100%    -> linear from `threshold_payout` up to 100% of target incentive
  attainment >= 100%                -> 100% + accelerator x (attainment - 100%), capped at `cap_payout`
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import text

from .config import Settings
from .db import get_engine, has_territories


class IncentiveError(ValueError):
    pass


PLAN_LIMITS = {  # key: (min, max) accepted for overrides
    "quota_growth_pct": (-50.0, 100.0), "target_incentive": (1.0, 1_000_000.0),
    "threshold_attainment": (0.05, 0.99), "threshold_payout": (0.0, 1.0),
    "accelerator": (0.0, 5.0), "cap_payout": (1.0, 5.0),
}


def resolve_plan(settings: Settings, overrides: dict | None = None) -> dict:
    plan = {k: float(settings.incentive[k]) for k in PLAN_LIMITS}
    plan["histogram_bin_pp"] = float(settings.incentive.get("histogram_bin_pp", 10))
    for k, v in (overrides or {}).items():
        if v is None:
            continue
        if k not in PLAN_LIMITS:
            raise IncentiveError(f"Unknown plan parameter: {k}")
        lo, hi = PLAN_LIMITS[k]
        if not lo <= float(v) <= hi:
            raise IncentiveError(f"{k} must be between {lo} and {hi}")
        plan[k] = float(v)
    return plan


def payout_fraction(attainment, plan: dict) -> np.ndarray:
    """Share of target incentive earned at the given attainment (1.0 = 100% attainment)."""
    a = np.asarray(attainment, dtype=float)
    t, tp = plan["threshold_attainment"], plan["threshold_payout"]
    mid = tp + (1.0 - tp) * (a - t) / (1.0 - t)
    above = 1.0 + plan["accelerator"] * (a - 1.0)
    out = np.where(a < t, 0.0, np.where(a < 1.0, mid, above))
    return np.minimum(out, plan["cap_payout"])


def _quarter_label(year: int, q: int) -> str:
    return f"{year}-Q{q}"


def _territory_months(settings: Settings) -> pd.DataFrame:
    with get_engine(settings).connect() as conn:
        df = pd.read_sql_query(text("SELECT territory_id, territory, rep_name, region, month, trx FROM v_territory_month"), conn)
    df["trx"] = df["trx"].astype(float)
    return df


def compute(settings: Settings, plan: dict, region: str | None = None, start: str | None = None,
            end: str | None = None, quarter: str | None = None) -> dict:
    if not has_territories(settings):
        raise IncentiveError("No territory data is loaded. Add territory.csv (see Data & reports) to enable incentive compensation.")
    df = _territory_months(settings)
    if region:
        df = df[df["region"] == region]
    if df.empty:
        raise IncentiveError("No territories match the selected region.")
    df = df.assign(year=df["month"].str[:4].astype(int), q=(df["month"].str[5:7].astype(int) - 1) // 3 + 1)
    qd = (df.groupby(["territory_id", "territory", "rep_name", "region", "year", "q"], as_index=False)
            .agg(trx=("trx", "sum"), months=("month", "nunique")))
    qd = qd[qd["months"] == 3]
    prior = qd[["territory_id", "year", "q", "trx"]].assign(year=lambda d: d["year"] + 1).rename(columns={"trx": "prior_trx"})
    rows = qd.merge(prior, on=["territory_id", "year", "q"], how="inner")
    rows["quarter"] = [_quarter_label(y, q) for y, q in zip(rows["year"], rows["q"])]
    rows["first_month"] = [f"{y}-{3 * (q - 1) + 1:02d}" for y, q in zip(rows["year"], rows["q"])]
    rows["last_month"] = [f"{y}-{3 * (q - 1) + 3:02d}" for y, q in zip(rows["year"], rows["q"])]
    if start:
        rows = rows[rows["first_month"] >= start]
    if end:
        rows = rows[rows["last_month"] <= end]
    rows = rows[rows["prior_trx"] > 0]
    if rows.empty:
        raise IncentiveError("No complete quarter with a prior-year comparison falls inside the selected period. "
                             "Quotas need the same quarter of the previous year.")

    econ_rev = float(settings.economics["revenue_per_trx"])
    rows = rows.assign(quota=rows["prior_trx"] * (1 + plan["quota_growth_pct"] / 100.0))
    rows["attainment"] = rows["trx"] / rows["quota"]
    rows["payout_fraction"] = payout_fraction(rows["attainment"], plan)
    rows["payout"] = rows["payout_fraction"] * plan["target_incentive"]
    rows["revenue"] = rows["trx"] * econ_rev

    n = len(rows)
    total_payout, total_rev = float(rows["payout"].sum()), float(rows["revenue"].sum())
    summary = {
        "territory_quarters": int(n), "territories": int(rows["territory_id"].nunique()),
        "quarters": int(rows["quarter"].nunique()),
        "weighted_attainment_pct": round(float(rows["trx"].sum() / rows["quota"].sum() * 100), 2),
        "avg_attainment_pct": round(float(rows["attainment"].mean() * 100), 2),
        "pct_at_or_above_target": round(float((rows["attainment"] >= 1).mean() * 100), 1),
        "pct_below_threshold": round(float((rows["attainment"] < plan["threshold_attainment"]).mean() * 100), 1),
        "total_payout": round(total_payout, 0),
        "target_payout": round(plan["target_incentive"] * n, 0),
        "payout_vs_target_pct": round(total_payout / (plan["target_incentive"] * n) * 100, 1),
        "cost_of_sales_pct": round(total_payout / total_rev * 100, 3) if total_rev else None,
    }

    by_q = []
    for qlabel, g in rows.groupby("quarter"):
        by_q.append({"quarter": qlabel, "territories": int(len(g)),
                     "attainment_pct": round(float(g["trx"].sum() / g["quota"].sum() * 100), 2),
                     "pct_at_or_above_target": round(float((g["attainment"] >= 1).mean() * 100), 1),
                     "total_payout": round(float(g["payout"].sum()), 0)})
    by_q.sort(key=lambda r: r["quarter"])

    chosen = quarter or by_q[-1]["quarter"]
    if chosen not in {r["quarter"] for r in by_q}:
        raise IncentiveError(f"Quarter {chosen} is not available. Choose one of: {', '.join(r['quarter'] for r in by_q)}")
    sel = rows[rows["quarter"] == chosen].sort_values(["attainment", "territory_id"], ascending=[False, True])
    territories = [{
        "territory": r.territory, "rep_name": r.rep_name, "region": r.region, "actual": round(r.trx, 0),
        "quota": round(r.quota, 0), "attainment_pct": round(r.attainment * 100, 1),
        "payout_pct": round(r.payout_fraction * 100, 1), "payout": round(r.payout, 0),
    } for r in sel.itertuples()]

    att_pp = rows["attainment"].to_numpy() * 100
    w = plan["histogram_bin_pp"]
    lo, hi = np.floor(att_pp.min() / w) * w, np.ceil(att_pp.max() / w) * w
    if hi <= lo:
        hi = lo + w
    edges = np.arange(lo, hi + w / 2, w)
    counts, _ = np.histogram(att_pp, bins=edges)
    hist = [{"label": f"{int(a)}–{int(b)}%", "lo": float(a), "hi": float(b), "count": int(c),
             "below_threshold": bool(b <= plan["threshold_attainment"] * 100)}
            for a, b, c in zip(edges[:-1], edges[1:], counts)]

    top = max(150.0, float(np.ceil(att_pp.max() / 10) * 10 + 10))
    xs = np.arange(0.0, top + 0.1, 5.0)
    curve = [{"attainment_pct": float(x), "payout_pct": round(float(f) * 100, 1)}
             for x, f in zip(xs, payout_fraction(xs / 100.0, plan))]

    return {"plan": plan, "summary": summary, "by_quarter": by_q, "quarter": chosen,
            "quarters": [r["quarter"] for r in by_q], "territories": territories,
            "histogram": hist, "curve": curve, "region": region}
