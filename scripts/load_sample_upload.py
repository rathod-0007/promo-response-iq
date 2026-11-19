"""Load samples/lipidex_prescriber_extract.csv through the same code path as the upload wizard.

It auto-maps the columns, names things the way a brand team would (Prescribers, Detail visits, State, Segment...)
and replaces the data currently loaded. Use it to see the app on a data set that is not the built-in synthetic one:

    python scripts/load_sample_upload.py            # uses DATABASE_URL / config.json
    python scripts/load_sample_upload.py --reset    # go back to the built-in synthetic data
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bi  # noqa: E402
from app.config import ROOT, load_settings  # noqa: E402
from app.db import init_db  # noqa: E402
from app.uploader import import_upload, inspect, save_upload  # noqa: E402

SAMPLE = ROOT / "samples" / "lipidex_prescriber_extract.csv"
OPTIONS = {
    "name": "Lipidex sample extract", "duplicates": "sum", "missing": "exclude",
    "labels": {"entity": "Prescriber", "entities": "Prescribers", "metric": "Rx", "region": "State", "specialty": "Specialty",
               "tier": "Segment", "territory": "Territory", "rep": "Rep",
               "channels": {"calls": "Detail visits", "samples": "Sample drops", "emails": "E-mails"}},
    "economics": {"revenue_per_trx": 285, "cost_per_call": 120, "cost_per_sample": 9, "cost_per_email": 1.5},
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="restore the built-in synthetic data instead")
    args = ap.parse_args()
    settings = load_settings()
    if args.reset:
        init_db(settings)
        print("Restored the built-in synthetic data.")
    else:
        upload_id = save_upload(settings, SAMPLE.name, SAMPLE.read_bytes())
        info = inspect(settings, upload_id)
        result = import_upload(settings, upload_id, info["suggested"], OPTIONS)
        print(f"Loaded '{result['name']}': {result['summary']}")
        for w in result["warnings"]:
            print(" -", w)
    bi.ensure_published(settings)
    print("BI analysis tables are up to date.")


if __name__ == "__main__":
    main()
