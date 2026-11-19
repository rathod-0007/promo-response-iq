"""Start the dashboard: python run.py [--reset-data] [--port 8000]"""
import argparse

import uvicorn

from app.config import load_settings
from app.db import get_engine, init_db
from app.importer import import_csv_dir


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reset-data", action="store_true", help="regenerate the warehouse from config.json")
    ap.add_argument("--import-dir", help="folder with hcp.csv, activity.csv, rx.csv to load instead of synthetic data")
    args = ap.parse_args()
    if args.import_dir:
        print("Imported:", import_csv_dir(load_settings(), args.import_dir))
    elif args.reset_data:
        init_db(load_settings(), reset=True)
    s = load_settings()
    print("Database:", get_engine(s).url.render_as_string(hide_password=True), "schema:", s.schema)
    uvicorn.run("app.main:get_app", factory=True, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
