"""Sales-force effectiveness: are calls aligned with prescribing potential?

Decile analysis (HCPs ranked by Rx), call-alignment score, response-based segmentation and the
most mis-aligned HCPs. All thresholds come from config.json ("targeting").
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SEGMENTS = {
    ("high", True): ("Invest", "High volume and call-responsive: protect and grow coverage"),
    ("high", False): ("Defend", "High volume but less responsive: keep current calls, avoid adding more"),
    ("low", True): ("Develop", "Low volume but responsive: test extra calls and digital channels"),
    ("low", False): ("Self-serve", "Low volume and less responsive: move to e-mail and remote"),
}


def _share(x: pd.Series) -> pd.Series:
    tot = float(x.sum())
    return x / tot if tot else x * 0.0


def analyze(totals: pd.DataFrame, cfg: dict, tier_beta: dict | None = None) -> dict:
    """totals: one row per HCP with hcp_id, name, tier, region, specialty, trx, calls."""
    if totals.empty:
        return {"summary": {}, "deciles": [], "segments": None, "under_served": [], "over_served": []}
    d = totals.copy()
    for c in ("trx", "calls"):
        d[c] = d[c].astype(float)
    d = d.sort_values(["trx", "hcp_id"], ascending=[False, True]).reset_index(drop=True)
    n_dec = max(1, min(int(cfg["deciles"]), len(d)))
    d["decile"] = (np.arange(len(d)) * n_dec // len(d)) + 1
    d["rx_share"], d["call_share"] = _share(d["trx"]), _share(d["calls"])

    over, under = float(cfg["over_index"]), float(cfg["under_index"])
    rows = []
    for dec, g in d.groupby("decile"):
        rx_s, call_s = float(g["rx_share"].sum()), float(g["call_share"].sum())
        idx = call_s / rx_s if rx_s > 0 else None
        action = "n/a" if idx is None else ("Over-served: trim calls" if idx > over
                                              else "Under-served: add calls" if idx < under else "Balanced")
        rows.append({"decile": int(dec), "hcps": int(len(g)), "trx": float(g["trx"].sum()), "calls": float(g["calls"].sum()),
                     "rx_share_pct": round(rx_s * 100, 1), "call_share_pct": round(call_s * 100, 1),
                     "trx_per_call": round(float(g["trx"].sum() / g["calls"].sum()), 2) if g["calls"].sum() else None,
                     "call_index": round(idx, 2) if idx is not None else None, "action": action})

    hv_n = min(int(cfg["high_volume_deciles"]), n_dec)
    high = d["decile"] <= hv_n
    alignment = 1.0 - 0.5 * float(np.abs(pd.Series([r["call_share_pct"] for r in rows]) -
                                         pd.Series([r["rx_share_pct"] for r in rows])).sum()) / 100.0
    summary = {
        "hcps": int(len(d)), "deciles": int(n_dec), "high_volume_deciles": hv_n,
        "top_rx_share_pct": round(float(d.loc[high, "rx_share"].sum() * 100), 1),
        "top_call_share_pct": round(float(d.loc[high, "call_share"].sum() * 100), 1),
        "alignment_score_pct": round(alignment * 100, 1),
    }

    segments = None
    if tier_beta:
        cut = float(np.median(list(tier_beta.values())))
        d["responsive"] = d["tier"].map(lambda t: tier_beta.get(t, 0.0) >= cut)
        d["volume"] = np.where(high, "high", "low")
        segments = []
        for (vol, resp), (name, advice) in SEGMENTS.items():
            g = d[(d["volume"] == vol) & (d["responsive"] == resp)]
            segments.append({"segment": name, "volume": vol, "responsive": bool(resp), "hcps": int(len(g)),
                             "rx_share_pct": round(float(g["rx_share"].sum() * 100), 1),
                             "call_share_pct": round(float(g["call_share"].sum() * 100), 1),
                             "calls_per_hcp": round(float(g["calls"].mean()), 1) if len(g) else None, "advice": advice})

    top_n = int(cfg["misaligned_top"])
    cols = ["hcp_id", "name", "tier", "region", "decile", "trx", "calls"]
    hv_median = float(d.loc[high, "calls"].median())
    under_df = d[high & (d["calls"] < hv_median)].sort_values(["trx", "hcp_id"], ascending=[False, True]).head(top_n)
    over_df = d[~high & (d["calls"] >= hv_median)].sort_values(["calls", "hcp_id"], ascending=[False, True]).head(top_n)
    to_rec = lambda df: df[cols].assign(trx=lambda x: x["trx"].round(0), calls=lambda x: x["calls"].round(0)).to_dict("records")
    return {"summary": summary, "deciles": rows, "segments": segments,
            "under_served": to_rec(under_df), "over_served": to_rec(over_df),
            "median_calls_high_volume": round(hv_median, 1)}
