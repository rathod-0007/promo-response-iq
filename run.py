"""Start the dashboard: python run.py [--reset-data] [--port 8000]"""
import argparse

import uvicorn

from app.config import load_settings
from app.db import init_db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reset-data", action="store_true", help="regenerate the warehouse from config.json")
    args = ap.parse_args()
    if args.reset_data:
        init_db(load_settings(), reset=True)
    uvicorn.run("app.main:get_app", factory=True, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
