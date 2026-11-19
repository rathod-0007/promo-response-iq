"""Create samples/lipidex_prescriber_extract.csv: a sample customer extract used to test the upload flow.

It deliberately looks nothing like the built-in synthetic data: different column names, a text date format
("Jul-2024"), four value tiers, a territory column, and a few real-world blemishes (blank cells, duplicate rows,
missing prescriber-months) so that mapping, cleaning and warnings are all exercised.

Run:  python scripts/make_sample_upload.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent.parent / "samples" / "lipidex_prescriber_extract.csv"
rng = np.random.default_rng(2025)

N, MONTHS = 420, pd.period_range("2024-07", "2025-12", freq="M")
STATES = ["CA", "TX", "FL", "NY", "IL", "OH", "PA"]
SPECIALTIES = ["Cardiology", "Internal Medicine", "Endocrinology"]
SEGMENTS = {"Platinum": (0.10, 18.0, 5.0), "Gold": (0.20, 9.0, 3.4), "Silver": (0.30, 4.5, 2.2), "Bronze": (0.40, 1.8, 1.0)}
ELASTICITY = {"Platinum": 0.12, "Gold": 0.24, "Silver": 0.20, "Bronze": 0.10}
TERR_PER_STATE = 4

seg_names = list(SEGMENTS)
seg = rng.choice(seg_names, N, p=[SEGMENTS[s][0] for s in seg_names])
state = rng.choice(STATES, N)
terr_no = np.array([rng.integers(1, TERR_PER_STATE + 1) for _ in range(N)])
potential = np.array([SEGMENTS[s][1] for s in seg]) * rng.lognormal(0, 0.3, N)
intensity = np.array([SEGMENTS[s][2] for s in seg]) * rng.lognormal(0, 0.35, N)
season = 1 + 0.06 * np.sin(2 * np.pi * (MONTHS.month.to_numpy() - 2) / 12)

visits = rng.poisson(intensity[:, None] * season[None, :], (N, len(MONTHS)))
samples = rng.poisson(visits * 1.2 + 0.2)
emails = rng.poisson(2.5, (N, len(MONTHS)))
ad = np.zeros_like(visits, dtype=float)
for t in range(len(MONTHS)):
    ad[:, t] = visits[:, t] + (0.45 * ad[:, t - 1] if t else 0.0)
beta = np.array([ELASTICITY[s] for s in seg])[:, None]
trend = np.exp(0.007 * np.arange(len(MONTHS)))[None, :]
mu = potential[:, None] * season[None, :] * trend * np.exp(beta * np.log1p(ad) + 0.04 * np.log1p(samples) + 0.02 * np.log1p(emails))
rx = rng.poisson(mu)

npi = 1000000000 + rng.choice(900000000, N, replace=False)  # 10-digit NPI-like ids (too big for int32)
rows = []
for i in range(N):
    terr = f"{state[i]}-{terr_no[i]:02d}"
    for t, m in enumerate(MONTHS):
        rows.append({"NPI": str(npi[i]), "Prescriber Name": f"Dr. {chr(65 + i % 26)}. Prescriber {i + 1:03d}",
                     "State": state[i], "Specialty Group": SPECIALTIES[i % len(SPECIALTIES)], "Segment": seg[i],
                     "Sales Territory": terr, "Rep": f"Rep {terr}", "Reporting Month": m.strftime("%b-%Y"),
                     "Total Rx": int(rx[i, t]), "Detail Visits": int(visits[i, t]),
                     "Sample Drops": int(samples[i, t]), "Email Sends": int(emails[i, t])})
df = pd.DataFrame(rows)

# real-world blemishes
df = df.drop(df.sample(frac=0.01, random_state=1).index)                            # some prescriber-months absent
df["Sample Drops"] = df["Sample Drops"].astype(object)
df.loc[df.sample(25, random_state=2).index, "Sample Drops"] = ""                    # blank cells
df = pd.concat([df, df.sample(6, random_state=3)], ignore_index=True).sort_values(["NPI", "Reporting Month"], kind="stable")
OUT.parent.mkdir(exist_ok=True)
df.to_csv(OUT, index=False)
print(f"wrote {OUT} ({len(df):,} rows, {df['NPI'].nunique()} prescribers)")
