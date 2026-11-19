"""Orchestration: model + optimiser with caching, auto-generated insights, full report."""
from __future__ import annotations

from . import analytics as an
from .config import Settings
from .db import data_version
from . import incentive as inc
from . import targeting as tg
from .db import has_territories
from .modeling import ModelResult, ModelError, channel_roi, fit_response_model, optimize_calls

_cache: dict = {}


def _db_stamp(settings: Settings) -> int:
    return data_version(settings)


def get_model(settings: Settings, f: an.Filters) -> tuple[ModelResult, object]:
    key = (settings.database_url, settings.schema, _db_stamp(settings), f.key())
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


def get_targeting(settings: Settings, f: an.Filters) -> dict:
    totals = an.hcp_totals(settings, f)
    beta, note = None, None
    try:
        beta = get_model(settings, f)[0].tier_beta
    except ModelError as e:  # not enough data for segmentation; deciles still work
        note = str(e)
    res = tg.analyze(totals, settings.targeting, beta)
    res["segments_note"] = note
    return res


def get_incentive(settings: Settings, overrides: dict, region=None, start=None, end=None, quarter=None) -> dict:
    plan = inc.resolve_plan(settings, overrides)
    return inc.compute(settings, plan, region, start, end, quarter)


def insights(kpi: dict, model: ModelResult, roi: list[dict], opt: dict, targeting: dict | None = None,
             incentive: dict | None = None) -> list[str]:
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
    sm = (targeting or {}).get("summary") or {}
    if sm:
        out.append(f"The top {sm['high_volume_deciles']} deciles deliver {sm['top_rx_share_pct']:.0f}% of Rx but receive "
                   f"{sm['top_call_share_pct']:.0f}% of calls (call alignment score {sm['alignment_score_pct']:.0f}%).")
    if incentive:
        i = incentive["summary"]
        out.append(f"{i['pct_at_or_above_target']:.0f}% of territory-quarters reach quota; the plan pays "
                   f"{i['payout_vs_target_pct']:.0f}% of target incentive ({i['cost_of_sales_pct']:.2f}% of Rx revenue).")
    if kpi.get("trx_change_pct_6m") is not None:
        out.append(f"Rx volume is {kpi['trx_change_pct_6m']:+.1f}% over the latest 6 months vs the prior 6.")
    return out


def build_report(settings: Settings, f: an.Filters, budget_change_pct: float = 0.0) -> dict:
    kpi = an.kpis(settings, f)
    model, _ = get_model(settings, f)
    roi = get_roi(settings, f)
    opt = get_optimization(settings, f, budget_change_pct)
    targeting = get_targeting(settings, f)
    incentive = None
    if has_territories(settings):
        try:
            incentive = get_incentive(settings, {}, f.region, f.start, f.end)
        except inc.IncentiveError:
            incentive = None
    return {
        "targeting": targeting, "incentive": incentive,
        "filters": f.__dict__, "kpis": kpi,
        "trend": an.trend(settings, f), "regions": an.breakdown(settings, f, "region"),
        "specialties": an.breakdown(settings, f, "specialty"), "tiers": an.breakdown(settings, f, "tier"),
        "model": model, "roi": roi, "optimization": opt,
        "insights": insights(kpi, model, roi, opt, targeting, incentive),
    }


__all__ = ["get_model", "get_roi", "get_optimization", "get_targeting", "get_incentive", "insights", "build_report", "ModelError"]
