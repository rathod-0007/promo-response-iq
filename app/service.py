"""Orchestration: model + optimiser with caching, auto-generated insights, full report."""
from __future__ import annotations

from . import analytics as an
from .config import Settings
from .modeling import ModelResult, ModelError, channel_roi, fit_response_model, optimize_calls

_cache: dict = {}


def _db_stamp(settings: Settings) -> float:
    return settings.db_path.stat().st_mtime


def get_model(settings: Settings, f: an.Filters) -> tuple[ModelResult, object]:
    key = (str(settings.db_path), _db_stamp(settings), f.key())
    if key not in _cache:
        panel = an.panel(settings, f)
        m = settings.model
        model = fit_response_model(panel, m["decay_grid"], m["min_observations"])
        _cache.clear() if len(_cache) > 32 else None
        _cache[key] = (model, panel)
    return _cache[key]


def get_roi(settings: Settings, f: an.Filters) -> list[dict]:
    model, panel = get_model(settings, f)
    return channel_roi(panel, model, settings.economics)


def get_optimization(settings: Settings, f: an.Filters, budget_change_pct: float) -> dict:
    model, panel = get_model(settings, f)
    m = settings.model
    return optimize_calls(panel, model, settings.economics, m["max_calls_per_hcp"], m["recent_months"], budget_change_pct)


def insights(kpi: dict, model: ModelResult, roi: list[dict], opt: dict) -> list[str]:
    out = []
    tb = {t: b for t, b in model.tier_beta.items()}
    if tb:
        top = max(tb, key=tb.get)
        low = min(tb, key=tb.get)
        out.append(f"Tier {top} HCPs are the most call-responsive (elasticity {tb[top]:.2f}); "
                   f"Tier {low} is the least ({tb[low]:.2f}).")
    out.append(f"Promotion effect carries over at a {model.decay:.0%} monthly decay "
               f"(within-HCP R² {model.r2_within:.2f}).")
    calls_roi = [r for r in roi if r["channel"] == "Calls" and r["roi"] is not None]
    if calls_roi:
        best = max(calls_roi, key=lambda r: r["roi"])
        out.append(f"Best call ROI is {best['scope']} at {best['roi']:.1f}x "
                   f"({best['incr_trx_per_unit']:.2f} incremental Rx per call).")
    s = opt["summary"]
    if s["uplift_pct"] is not None:
        out.append(f"Reallocating calls at {opt['budget_change_pct']:+.0f}% budget lifts monthly Rx by "
                   f"{s['uplift_pct']:.1f}% ({s['incremental_trx']:+.0f} Rx, net value ${s['net_value']:,.0f}).")
    if kpi.get("trx_change_pct_6m") is not None:
        out.append(f"Rx volume is {kpi['trx_change_pct_6m']:+.1f}% over the latest 6 months vs the prior 6.")
    return out


def build_report(settings: Settings, f: an.Filters, budget_change_pct: float = 0.0) -> dict:
    kpi = an.kpis(settings, f)
    model, _ = get_model(settings, f)
    roi = get_roi(settings, f)
    opt = get_optimization(settings, f, budget_change_pct)
    return {
        "filters": f.__dict__, "kpis": kpi,
        "trend": an.trend(settings, f), "regions": an.breakdown(settings, f, "region"),
        "specialties": an.breakdown(settings, f, "specialty"), "tiers": an.breakdown(settings, f, "tier"),
        "model": model, "roi": roi, "optimization": opt,
        "insights": insights(kpi, model, roi, opt),
    }


__all__ = ["get_model", "get_roi", "get_optimization", "insights", "build_report", "ModelError"]
