import numpy as np
import pytest

from app import analytics as an
from app.modeling import ModelError, adstock, channel_roi, fit_response_model, optimize_calls


@pytest.fixture(scope="module")
def fitted(settings):
    panel = an.panel(settings, an.Filters())
    model = fit_response_model(panel, settings.model["decay_grid"], settings.model["min_observations"])
    return panel, model


def test_adstock_recursion():
    out = adstock(np.array([[1.0, 0.0, 2.0]]), 0.5)
    assert out.tolist() == [[1.0, 0.5, 2.25]]


def test_model_recovers_true_elasticities(settings, fitted):
    _, model = fitted
    truth = settings.simulation["true_call_elasticity"]
    for tier, true_b in truth.items():
        assert abs(model.tier_beta[tier] - true_b) < 0.08, (tier, model.tier_beta[tier], true_b)
    assert max(model.tier_beta, key=model.tier_beta.get) == max(truth, key=truth.get)
    assert model.decay == settings.simulation["true_decay"]
    assert 0 < model.r2_within < 1


def test_model_terms_and_confidence_intervals(fitted):
    _, model = fitted
    for t in model.terms:
        assert t["ci_low"] <= t["coef"] <= t["ci_high"]
        assert t["se"] >= 0


def test_model_rejects_small_samples(settings):
    panel = an.panel(settings, an.Filters(region="West", tier="A", start="2024-01", end="2024-02"))
    with pytest.raises(ModelError):
        fit_response_model(panel, [0.5], 200)


def test_roi_rows(settings, fitted):
    panel, model = fitted
    roi = channel_roi(panel, model, settings.economics)
    assert {r["channel"] for r in roi} == {"calls", "samples", "emails"}
    assert all(r["incr_trx_per_unit"] >= 0 and r["roi"] is not None for r in roi)


def test_optimizer_conserves_budget_and_never_loses_rx(settings, fitted):
    panel, model = fitted
    m = settings.model
    opt = optimize_calls(panel, model, settings.economics, m["max_calls_per_hcp"], m["recent_months"], 0)
    s = opt["summary"]
    assert abs(s["recommended_calls"] - round(s["current_calls"])) <= 1
    assert s["incremental_trx"] >= -1e-6
    plan = opt["plan"]
    assert plan["recommended_calls"].max() <= m["max_calls_per_hcp"] and plan["recommended_calls"].min() >= 0
    assert plan["recommended_calls"].sum() == s["recommended_calls"]


def test_optimizer_budget_monotonic(settings, fitted):
    panel, model = fitted
    m = settings.model
    run = lambda pct: optimize_calls(panel, model, settings.economics, m["max_calls_per_hcp"], m["recent_months"], pct)["summary"]
    lo, mid, hi = run(-20), run(0), run(20)
    assert lo["expected_trx"] <= mid["expected_trx"] <= hi["expected_trx"]
    assert lo["recommended_calls"] < mid["recommended_calls"] < hi["recommended_calls"]


def test_optimizer_favours_responsive_tiers(settings, fitted):
    panel, model = fitted
    m = settings.model
    by_tier = {r["tier"]: r for r in optimize_calls(panel, model, settings.economics, m["max_calls_per_hcp"],
                                                    m["recent_months"], 0)["by_tier"]}
    worst = min(model.tier_beta, key=model.tier_beta.get)
    best = max(model.tier_beta, key=model.tier_beta.get)
    assert by_tier[best]["recommended_calls"] / by_tier[best]["current_calls"] >= \
        by_tier[worst]["recommended_calls"] / by_tier[worst]["current_calls"]
