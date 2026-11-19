"""Synthetic but realistic HCP activity / prescription generator with known ground truth.

Rx follows a log-linear response to adstocked calls (per tier), samples and e-mails, HCP-level
potential, seasonality and trend, with Poisson noise. The truth lives in config.json so tests can
check the model recovers it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def month_labels(start: str, n: int) -> list[str]:
    return [str(p) for p in pd.period_range(start=start, periods=n, freq="M")]


def make_territories(sim: dict) -> pd.DataFrame:
    """Sales territories (one rep each), derived only from config so they are reproducible."""
    n = int(sim["territories_per_region"])
    rows = []
    for ri, region in enumerate(sim["regions"]):
        for k in range(1, n + 1):
            rows.append({"territory_id": ri * n + k, "name": f"{region} {k:02d}",
                         "region": region, "rep_name": f"Rep {region} {k:02d}"})
    return pd.DataFrame(rows, columns=["territory_id", "name", "region", "rep_name"])


def _assign_territories(sim: dict, hcp: pd.DataFrame) -> pd.Series:
    """Spread each region's HCPs evenly over that region's territories (separate RNG stream)."""
    rng = np.random.default_rng([sim["seed"], 1])
    terr = make_territories(sim)
    out = pd.Series(0, index=hcp.index, dtype="int64")
    for region, grp in hcp.groupby("region"):
        ids = terr.loc[terr["region"] == region, "territory_id"].to_numpy()
        order = rng.permutation(len(grp))
        out.loc[grp.index[order]] = ids[np.arange(len(grp)) % len(ids)]
    return out


def generate(sim: dict):
    rng = np.random.default_rng(sim["seed"])
    n, T = sim["n_hcps"], sim["n_months"]
    tiers = list(sim["tier_share"])
    probs = np.array([sim["tier_share"][t] for t in tiers], dtype=float)
    probs /= probs.sum()

    tier = rng.choice(tiers, size=n, p=probs)
    hcp = pd.DataFrame({
        "hcp_id": np.arange(1, n + 1),
        "name": [f"Dr. HCP-{i:04d}" for i in range(1, n + 1)],
        "specialty": rng.choice(sim["specialties"], size=n),
        "region": rng.choice(sim["regions"], size=n),
        "tier": tier,
    })

    hcp["territory_id"] = _assign_territories(sim, hcp)

    potential = np.array([sim["potential_mean"][t] for t in tier]) * rng.lognormal(0, 0.35, n)
    intensity = np.array([sim["mean_calls"][t] for t in tier]) * rng.lognormal(0, 0.4, n)

    months = month_labels(sim["start_month"], T)
    cal_month = np.array([int(m[5:7]) for m in months])
    season = np.array(sim["seasonality"])[cal_month - 1]
    trend = np.exp(sim["monthly_trend"] * np.arange(T))

    calls = rng.poisson(intensity[:, None] * season[None, :] ** 0.5, size=(n, T))
    samples = rng.poisson(calls * 1.5 + 0.3)
    emails = rng.poisson(3.0, size=(n, T))

    d = sim["true_decay"]
    ad = np.zeros((n, T))
    for t in range(T):
        ad[:, t] = calls[:, t] + (d * ad[:, t - 1] if t else 0.0)

    beta_call = np.array([sim["true_call_elasticity"][t] for t in tier])[:, None]
    log_mu = (np.log(potential)[:, None] + np.log(season)[None, :] + np.log(trend)[None, :]
              + beta_call * np.log1p(ad)
              + sim["true_sample_elasticity"] * np.log1p(samples)
              + sim["true_email_elasticity"] * np.log1p(emails))
    trx = rng.poisson(np.exp(log_mu))

    ids = np.repeat(hcp["hcp_id"].to_numpy(), T)
    mon = np.tile(months, n)
    activity = pd.DataFrame({"hcp_id": ids, "month": mon, "calls": calls.ravel(),
                             "samples": samples.ravel(), "emails": emails.ravel()})
    rx = pd.DataFrame({"hcp_id": ids, "month": mon, "trx": trx.ravel()})
    return hcp, activity, rx
