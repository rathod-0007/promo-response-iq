import copy

import pytest

from app import analytics as an
from app.config import Settings
from app.datagen import generate
from app.importer import ImportError_, import_csv_dir


@pytest.fixture()
def csv_dir(settings, tmp_path):
    hcp, act, rx = generate({**settings.simulation, "n_hcps": 30, "n_months": 6})
    hcp.to_csv(tmp_path / "hcp.csv", index=False)
    act.to_csv(tmp_path / "activity.csv", index=False)
    rx.to_csv(tmp_path / "rx.csv", index=False)
    return tmp_path


def _fresh(settings, tmp_path):
    return Settings(db_path=tmp_path / "imp.db", simulation=copy.deepcopy(settings.simulation),
                    economics=settings.economics, model=settings.model)


def test_import_loads_and_is_queryable(settings, csv_dir, tmp_path):
    s = _fresh(settings, tmp_path)
    res = import_csv_dir(s, csv_dir)
    assert res == {"hcps": 30, "activity_rows": 180, "rx_rows": 180}
    assert an.kpis(s, an.Filters())["active_hcps"] == 30


def test_import_rejects_missing_columns(settings, csv_dir, tmp_path):
    (csv_dir / "rx.csv").write_text("hcp_id,month\n1,2024-01\n")
    with pytest.raises(ImportError_, match="missing columns"):
        import_csv_dir(_fresh(settings, tmp_path), csv_dir)


def test_import_rejects_missing_file(settings, tmp_path):
    with pytest.raises(ImportError_, match="Missing file"):
        import_csv_dir(_fresh(settings, tmp_path), tmp_path)


def test_import_rejects_unknown_hcp_and_keeps_existing_db(settings, csv_dir, tmp_path):
    s = _fresh(settings, tmp_path)
    import_csv_dir(s, csv_dir)
    (csv_dir / "rx.csv").write_text("hcp_id,month,trx\n9999,2024-01,3\n")
    with pytest.raises(ImportError_, match="not in hcp.csv"):
        import_csv_dir(s, csv_dir)
    assert an.kpis(s, an.Filters())["active_hcps"] == 30


def test_import_rejects_bad_values(settings, csv_dir, tmp_path):
    s = _fresh(settings, tmp_path)
    (csv_dir / "rx.csv").write_text("hcp_id,month,trx\n1,2024-01,-5\n")
    with pytest.raises(ImportError_, match="validation"):
        import_csv_dir(s, csv_dir)
    assert not s.db_path.exists()
