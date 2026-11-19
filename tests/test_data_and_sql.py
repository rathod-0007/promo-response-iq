import pytest
from sqlalchemy.exc import IntegrityError

from app import analytics as an
from app.datagen import generate, month_labels


def test_generator_is_deterministic_and_shaped(settings):
    a = generate(settings.simulation)
    b = generate(settings.simulation)
    sim = settings.simulation
    assert len(a[0]) == sim["n_hcps"]
    assert len(a[1]) == len(a[2]) == sim["n_hcps"] * sim["n_months"]
    for x, y in zip(a, b):
        assert x.equals(y)
    assert (a[1][["calls", "samples", "emails"]] >= 0).all().all()
    assert set(a[0]["tier"]) == {"A", "B", "C"}


def test_month_labels():
    assert month_labels("2024-11", 3) == ["2024-11", "2024-12", "2025-01"]


def test_schema_constraints(sql):
    with pytest.raises(IntegrityError):
        sql("INSERT INTO activity VALUES (1, '2024-01', -1, 0, 0)")      # negative calls
    with pytest.raises(IntegrityError):
        sql("INSERT INTO activity VALUES (99999, '2030-01', 1, 0, 0)")   # unknown HCP
    with pytest.raises(IntegrityError):
        sql("INSERT INTO rx VALUES (1, '2024-13', 1)")                   # bad month
    with pytest.raises(IntegrityError):
        sql("INSERT INTO rx VALUES (1, '2024-01', 1), (1, '2024-01', 2)")  # duplicate key


def test_views_reconcile_with_tables(sql):
    tot_rx = sql("SELECT SUM(trx) FROM rx")[0][0]
    tot_view = sql("SELECT SUM(trx) FROM v_monthly_summary")[0][0]
    reg_view = sql("SELECT SUM(trx) FROM v_region_summary")[0][0]
    assert tot_rx == tot_view == reg_view


def test_region_view_ratio_is_float(sql):
    row = sql("SELECT trx, calls, trx_per_call FROM v_region_summary LIMIT 1")[0]
    assert isinstance(row[2], float) and abs(row[2] - row[0] / row[1]) < 1e-3


def test_kpis_match_direct_sums(settings):
    k = an.kpis(settings, an.Filters())
    p = an.panel(settings, an.Filters())
    assert k["total_trx"] == int(p["trx"].sum())
    assert k["total_calls"] == int(p["calls"].sum())
    assert k["active_hcps"] == p["hcp_id"].nunique()
    assert k["trx_per_call"] == round(p["trx"].sum() / p["calls"].sum(), 3)


def test_filters_apply(settings):
    f = an.Filters(region="West", tier="A", start="2024-06", end="2024-08")
    p = an.panel(settings, f)
    assert set(p["region"]) == {"West"} and set(p["tier"]) == {"A"}
    assert p["month"].min() >= "2024-06" and p["month"].max() <= "2024-08"
    assert an.kpis(settings, f)["total_trx"] == int(p["trx"].sum())


def test_filter_values_are_parameterised(settings):
    f = an.Filters(region="West'; DROP TABLE hcp; --")
    assert an.kpis(settings, f)["total_trx"] == 0
    assert an.meta(settings)["regions"]  # table still intact


def test_breakdown_totals_and_whitelist(settings):
    df = an.breakdown(settings, an.Filters(), "region")
    assert int(df["trx"].sum()) == an.kpis(settings, an.Filters())["total_trx"]
    with pytest.raises(ValueError):
        an.breakdown(settings, an.Filters(), "name; DROP TABLE hcp")


def test_top_hcps_sorted(settings):
    df = an.top_hcps(settings, an.Filters(region="West"), 5)
    assert len(df) == 5 and df["trx"].is_monotonic_decreasing and set(df["region"]) == {"West"}


def test_trend_has_all_months(settings):
    assert len(an.trend(settings, an.Filters())) == settings.simulation["n_months"]
