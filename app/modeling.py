"""Promotion-response model (HCP fixed-effects, log-log with adstock) and call-allocation optimiser."""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

T_CRIT = 1.96  # large-sample normal approximation for 95% intervals


class ModelError(ValueError):
    pass


def _matrices(panel: pd.DataFrame):
    """Balanced HCP x month matrices (missing months filled with zeros)."""
    hcps = sorted(panel["hcp_id"].unique())
    months = sorted(panel["month"].unique())
    idx = pd.MultiIndex.from_product([hcps, months], names=["hcp_id", "month"])
    full = panel.set_index(["hcp_id", "month"]).reindex(idx)
    tier = panel.drop_duplicates("hcp_id").set_index("hcp_id")["tier"].reindex(hcps).to_numpy()
    shape = (len(hcps), len(months))
    get = lambda c: full[c].fillna(0).to_numpy(dtype=float).reshape(shape)
    return hcps, months, tier, get("calls"), get("samples"), get("emails"), get("trx")


def adstock(calls: np.ndarray, decay: float) -> np.ndarray:
    out = np.zeros_like(calls, dtype=float)
    for t in range(calls.shape[1]):
        out[:, t] = calls[:, t] + (decay * out[:, t - 1] if t else 0.0)
    return out


@dataclass
class ModelResult:
    decay: float
    r2_within: float
    n_obs: int
    n_hcps: int
    terms: list = field(default_factory=list)  # dicts: term, coef, se, t, ci_low, ci_high
    tier_beta: dict = field(default_factory=dict)
    sample_beta: float = 0.0
    email_beta: float = 0.0
    decay_scores: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "decay": self.decay, "r2_within": round(self.r2_within, 4), "n_obs": self.n_obs,
            "n_hcps": self.n_hcps, "terms": self.terms, "tier_beta": self.tier_beta,
            "sample_beta": self.sample_beta, "email_beta": self.email_beta,
            "decay_scores": {str(k): round(v, 4) for k, v in self.decay_scores.items()},
        }


def _fit_once(tier, calls, samples, emails, trx, decay):
    n, T = trx.shape
    tiers = sorted(set(tier))
    y = np.log1p(trx)
    ad = np.log1p(adstock(calls, decay))
    cols, names = [], []
    for t in tiers:
        cols.append(ad * (tier == t)[:, None])
        names.append(f"calls_tier_{t}")
    cols += [np.log1p(samples), np.log1p(emails)]
    names += ["samples", "emails"]
    n_ctrl = len(cols)
    for m in range(1, T):  # month dummies absorb seasonality and trend
        d = np.zeros((n, T))
        d[:, m] = 1.0
        cols.append(d)
    X = np.stack([c.ravel() for c in cols], axis=1)
    yv = y.ravel()
    # within transformation (HCP fixed effects)
    Xd = X - np.repeat(X.reshape(n, T, -1).mean(axis=1), T, axis=0)
    yd = yv - np.repeat(y.mean(axis=1), T)
    beta, *_ = np.linalg.lstsq(Xd, yd, rcond=None)
    resid = yd - Xd @ beta
    ss_res, ss_tot = float(resid @ resid), float(yd @ yd)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    dof = max(n * T - n - Xd.shape[1], 1)
    cov = (ss_res / dof) * np.linalg.pinv(Xd.T @ Xd)
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    return names, beta[:n_ctrl], se[:n_ctrl], r2


def fit_response_model(panel: pd.DataFrame, decay_grid, min_obs: int = 200) -> ModelResult:
    if len(panel) < min_obs:
        raise ModelError(f"Not enough observations to fit the model ({len(panel)} < {min_obs}). Widen the filters.")
    hcps, months, tier, calls, samples, emails, trx = _matrices(panel)
    if len(months) < 4:
        raise ModelError("At least 4 months of data are required to fit the model.")
    best, scores = None, {}
    for d in decay_grid:
        names, b, se, r2 = _fit_once(tier, calls, samples, emails, trx, d)
        scores[d] = r2
        if best is None or r2 > best[0]:
            best = (r2, d, names, b, se)
    r2, d, names, b, se = best
    terms = [{"term": n, "coef": round(float(c), 4), "se": round(float(s), 4),
              "t": round(float(c / s), 2) if s > 0 else None,
              "ci_low": round(float(c - T_CRIT * s), 4), "ci_high": round(float(c + T_CRIT * s), 4)}
             for n, c, s in zip(names, b, se)]
    coef = dict(zip(names, (float(x) for x in b)))
    return ModelResult(
        decay=d, r2_within=r2, n_obs=int(trx.size), n_hcps=len(hcps), terms=terms,
        tier_beta={n.rsplit("_", 1)[1]: round(v, 4) for n, v in coef.items() if n.startswith("calls_tier_")},
        sample_beta=round(coef["samples"], 4), email_beta=round(coef["emails"], 4), decay_scores=scores,
    )


def channel_roi(panel: pd.DataFrame, model: ModelResult, econ: dict) -> list[dict]:
    """Marginal incremental Rx and ROI of one extra unit of each channel (carry-over included for calls)."""
    carry = 1.0 / (1.0 - model.decay) if model.decay < 1 else 1.0
    _, _, tier, calls, samples, emails, trx = _matrices(panel)
    ad = adstock(calls, model.decay)
    rows = []

    def add(channel, scope, mult, beta, base, cost):
        incr = float(np.mean((trx[mult] + 1.0) * max(beta, 0.0) / (1.0 + base[mult]))) * (carry if channel == "Calls" else 1.0)
        value = incr * econ["revenue_per_trx"]
        rows.append({"channel": channel, "scope": scope, "incr_trx_per_unit": round(incr, 4),
                     "value_per_unit": round(value, 2), "cost_per_unit": cost,
                     "roi": round(value / cost, 2) if cost else None})

    for t, beta in sorted(model.tier_beta.items()):
        add("Calls", f"Tier {t}", (tier == t)[:, None] & np.ones_like(trx, dtype=bool), beta, ad, econ["cost_per_call"])
    allm = np.ones_like(trx, dtype=bool)
    add("Samples", "All", allm, model.sample_beta, samples, econ["cost_per_sample"])
    add("E-mails", "All", allm, model.email_beta, emails, econ["cost_per_email"])
    return rows


def optimize_calls(panel: pd.DataFrame, model: ModelResult, econ: dict, max_calls: int,
                   recent_months: int, budget_change_pct: float = 0.0) -> dict:
    """Greedy marginal allocation of the monthly call budget; exact for concave response curves."""
    hcps, months, tier, calls, _, _, trx = _matrices(panel)
    k = max(1, min(recent_months, len(months)))
    c0, y0 = calls[:, -k:].mean(axis=1), trx[:, -k:].mean(axis=1)
    beta = np.array([max(model.tier_beta.get(t, 0.0), 0.0) for t in tier])
    s = 1.0 / (1.0 - model.decay) if model.decay < 1 else 1.0  # steady-state adstock multiplier
    A = y0 / np.power(1.0 + s * c0, beta)

    def f(i, c):
        return A[i] * (1.0 + s * c) ** beta[i]

    n = len(hcps)
    budget = int(round(float(c0.sum()) * (1.0 + budget_change_pct / 100.0)))
    budget = max(0, min(budget, n * max_calls))
    alloc = np.zeros(n, dtype=int)
    heap = [(-(f(i, 1) - f(i, 0)), i) for i in range(n) if max_calls >= 1]
    heapq.heapify(heap)
    for _ in range(budget):
        if not heap:
            break
        _, i = heapq.heappop(heap)
        alloc[i] += 1
        if alloc[i] < max_calls:
            heapq.heappush(heap, (-(f(i, alloc[i] + 1) - f(i, alloc[i])), i))

    trx_new = np.array([f(i, alloc[i]) for i in range(n)])
    meta = panel.drop_duplicates("hcp_id").set_index("hcp_id").reindex(hcps)
    plan = pd.DataFrame({
        "hcp_id": hcps, "region": meta["region"].to_numpy(), "specialty": meta["specialty"].to_numpy(),
        "tier": tier, "current_calls": np.round(c0, 2), "recommended_calls": alloc,
        "delta_calls": np.round(alloc - c0, 2), "expected_trx_current": np.round(y0, 2),
        "expected_trx_new": np.round(trx_new, 2),
    })
    plan["delta_trx"] = (plan["expected_trx_new"] - plan["expected_trx_current"]).round(2)
    by_tier = (plan.groupby("tier").agg(hcps=("hcp_id", "count"), current_calls=("current_calls", "sum"),
                                         recommended_calls=("recommended_calls", "sum"),
                                         trx_current=("expected_trx_current", "sum"),
                                         trx_new=("expected_trx_new", "sum")).round(1).reset_index())
    cur_calls, new_calls = float(c0.sum()), int(alloc.sum())
    cur_trx, new_trx = float(y0.sum()), float(trx_new.sum())
    d_trx = new_trx - cur_trx
    return {
        "budget_change_pct": budget_change_pct,
        "summary": {
            "current_calls": round(cur_calls, 1), "recommended_calls": new_calls,
            "current_trx": round(cur_trx, 1), "expected_trx": round(new_trx, 1),
            "incremental_trx": round(d_trx, 1),
            "uplift_pct": round(d_trx / cur_trx * 100, 2) if cur_trx else None,
            "incremental_revenue": round(d_trx * econ["revenue_per_trx"], 0),
            "call_cost_change": round((new_calls - cur_calls) * econ["cost_per_call"], 0),
            "net_value": round(d_trx * econ["revenue_per_trx"] - (new_calls - cur_calls) * econ["cost_per_call"], 0),
        },
        "by_tier": by_tier.to_dict("records"),
        "plan": plan,
    }
