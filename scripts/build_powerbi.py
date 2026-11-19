"""Build the Power BI project from whatever data set is loaded.

    python scripts/build_powerbi.py        # writes bi/powerbi/PromoResponseIQ.pbip (+ the CSVs it reads)

Open the .pbip in Power BI Desktop (free), then Home > Refresh.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bi_powerbi  # noqa: E402
from app.config import load_settings  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", default=str(bi_powerbi.OUT))
a = ap.parse_args()
r = bi_powerbi.generate(load_settings(), Path(a.out))
print(f"Wrote {r['project']}: {r['tables']} tables, {r['relationships']} relationships, {r['pages']} pages, {r['visuals']} visuals")
