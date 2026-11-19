import pytest
from sqlalchemy import text

from app import analytics as an
from app.datagen import generate
from app.db import get_engine, is_loaded
from app.importer import ImportError_, import_csv_dir


def write_rx(folder, *rows):
    lines = ["hcp_id,month,trx", *rows]
    (folder / "rx.csv").write_text("\n".join(lines) + "\n")


@pytest.fixture()
def csv_dir(scratch_settings, tmp_path):
    hcp, act, rx = generate(scratch_settings.simulation)
    hcp.to_csv(tmp_path / "hcp.csv", index=False)
    act.to_csv(tmp_path / "activity.csv", index=False)
    rx.to_csv(tmp_path / "rx.csv", index=False)
    return tmp_path


def test_import_loads_and_is_queryable(scratch_settings, csv_dir):
    res = import_csv_dir(scratch_settings, csv_dir)
    assert res == {"hcps": 30, "activity_rows": 180, "rx_rows": 180}
    assert an.kpis(scratch_settings, an.Filters())["active_hcps"] == 30
    with get_engine(scratch_settings).connect() as c:
        source = c.execute(text("SELECT source FROM data_load ORDER BY load_id DESC LIMIT 1")).scalar()
    assert source.startswith("csv:")


def test_reimport_replaces_data(scratch_settings, csv_dir):
    import_csv_dir(scratch_settings, csv_dir)
    import_csv_dir(scratch_settings, csv_dir)
    assert an.panel(scratch_settings, an.Filters()).shape[0] == 180


def test_import_rejects_missing_columns(scratch_settings, csv_dir):
    (csv_dir / "rx.csv").write_text("hcp_id,month\n1,2024-01\n")
    with pytest.raises(ImportError_, match="missing columns"):
        import_csv_dir(scratch_settings, csv_dir)


def test_import_rejects_missing_file(scratch_settings, tmp_path):
    with pytest.raises(ImportError_, match="Missing file"):
        import_csv_dir(scratch_settings, tmp_path)


def test_import_rejects_duplicate_keys(scratch_settings, csv_dir):
    write_rx(csv_dir, "1,2024-01,3", "1,2024-01,4")
    with pytest.raises(ImportError_, match="duplicate"):
        import_csv_dir(scratch_settings, csv_dir)


def test_unknown_hcp_rejected_and_existing_data_kept(scratch_settings, csv_dir):
    import_csv_dir(scratch_settings, csv_dir)
    write_rx(csv_dir, "9999,2024-01,3")
    with pytest.raises(ImportError_, match="not in hcp.csv"):
        import_csv_dir(scratch_settings, csv_dir)
    assert an.kpis(scratch_settings, an.Filters())["active_hcps"] == 30


def test_db_level_failure_rolls_back_everything(scratch_settings, csv_dir):
    import_csv_dir(scratch_settings, csv_dir)
    before = an.kpis(scratch_settings, an.Filters())["total_trx"]
    write_rx(csv_dir, "1,2024-01,-5")
    with pytest.raises(ImportError_, match="validation"):
        import_csv_dir(scratch_settings, csv_dir)
    assert an.kpis(scratch_settings, an.Filters())["total_trx"] == before


def test_failed_first_import_leaves_nothing(scratch_settings, csv_dir):
    write_rx(csv_dir, "1,2024-13,5")
    with pytest.raises(ImportError_, match="validation"):
        import_csv_dir(scratch_settings, csv_dir)
    assert not is_loaded(scratch_settings)
