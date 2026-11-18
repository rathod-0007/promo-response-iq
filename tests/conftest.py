import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ROOT, Settings  # noqa: E402
from app.db import init_db  # noqa: E402


@pytest.fixture(scope="session")
def settings(tmp_path_factory) -> Settings:
    raw = json.loads((ROOT / "config.json").read_text())
    db = tmp_path_factory.mktemp("db") / "test.db"
    s = Settings(db_path=db, simulation=copy.deepcopy(raw["simulation"]),
                 economics=raw["economics"], model=raw["model"])
    init_db(s)
    return s
