"""Build the Tableau workbook from whatever data set is loaded.

    python scripts/build_tableau.py        # writes bi/tableau/RxLift.twbx (+ .twb and the extracts it reads)

Needs:  pip install -r requirements-bi.txt
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bi_tableau  # noqa: E402
from app.config import load_settings  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", default=str(bi_tableau.OUT))
ap.add_argument("--sheets", type=int, default=None, help="debug: build only the first N charts")
ap.add_argument("--no-dashboards", action="store_true", help="debug: worksheets only")
a = ap.parse_args()
r = bi_tableau.generate(load_settings(), Path(a.out), a.sheets, not a.no_dashboards)
print(f"Exported {r['tables']} BI tables. Wrote {r['workbook']} and {r['package']}")
for n in r["notes"]:
    print(" -", n)
