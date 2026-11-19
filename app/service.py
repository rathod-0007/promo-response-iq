"""Orchestration: model + optimiser with caching, auto-generated insights, full report.

Everything user-facing is phrased with the labels of the loaded data set (see profile.py), and economics
come from the data set's profile when the uploader supplied them.
"""
from __future__ import annotations

from . import analytics as an
from . import incentive as inc
from . import targeting as tg
from .config import Settings
from .db import data_version, has_territories
from .modeling import ModelError, ModelResult, channel_roi, fit_response_model, optimize_calls
from .profile import effective_economics, get_profile, tier_name, tokens

_cache: dict = {}


def get_model(settings: Settings, f: an.Filters) -> tuple[ModelResult, object]:
    key = (settings.database_url, settings.schema, data_version(settings), f.key())
    if key not in _cache:
        panel = an.panel(settings, f)
        m = settings.model
        model = fit_response_model(panel, m["decay_grid"], m["min_observations"])
        if len(_cache) > 32:
            _cache.clear()
        _cache[key] = (model, panel)
    return _cache[key]


def get_roi(settings: Settings, f: an.Filters) -> list[dict]:
    model, panel = get_model(settings, f)
    return channel_roi(panel, model, effective_economics(settings))


def get_optimization(settings: Settings, f: an.Filters, budget_change_pct: float) -> dict:
    model, panel = get_model(settings, f)
    m = settings.model
    opt = optimize_calls(panel, model, effective_economics(settings), m["max_calls_per_hcp"], m["recent_months"], budget_change_pct)
    plan = opt["plan"]
    plan.insert(1, "name", plan["hcp_id"].map(an.hcp_names(settings)))
    return opt


def get_targeting(settings: Settings, f: an.Filters) -> dict:
    totals = an.hcp_totals(settings, f)
    beta, note = None, None
    try:
        beta = get_model(settings, f)[0].tier_beta
    except ModelError as e:  # not enough data for segmentation; deciles still work
        note = str(e)
    res = tg.analyze(totals, settings.targeting, beta, tokens(get_profile(settings)))
    res["segments_note"] = note
    return res


def get_incentive(settings: Settings, overrides: dict, region=None, start=None, end=None, quarter=None) -> dict:
    plan = inc.resolve_plan(settings, overrides)
    return inc.compute(settings, plan, region, start, end, quarter)


def insights(kpi: dict, model: ModelResult, roi: list[dict], opt: dict, targeting: dict | None,
             incentive: dict | None, profile: dict) -> list[str]:
    t = tokens(profile)
    out = []
    tb = dict(model.tier_beta)
    if len(tb) == 1:
        (only, beta), = tb.items()
        out.append(f"{tier_name(profile, only)} {t['entities_l']} respond to {t['primary_l']} with an elasticity of {beta:.2f}.")
    elif tb:
        top, low = max(tb, key=tb.get), min(tb, key=tb.get)
        out.append(f"{tier_name(profile, top)} {t['entities_l']} respond most to {t['primary_l']} (elasticity {tb[top]:.2f}); "
                   f"{tier_name(profile, low)} respond least ({tb[low]:.2f}).")
    out.append(f"Promotion effect carries over at a {model.decay:.0%} monthly decay "
               f"(within-{t['entity']} R² {model.r2_within:.2f}).")
    primary_roi = [r for r in roi if r["channel"] == "calls" and r["roi"] is not None]
    if primary_roi:
        best = max(primary_roi, key=lambda r: r["roi"])
        out.append(f"Best {t['primary_l']} ROI is {tier_name(profile, best['scope'])} at {best['roi']:.1f}x "
                   f"({best['incr_trx_per_unit']:.2f} incremental {t['metric']} per {t['primary_unit']}).")
    s = opt["summary"]
    if s["uplift_pct"] is not None:
        out.append(f"Reallocating {t['primary_l']} at {opt['budget_change_pct']:+.0f}% budget lifts monthly {t['metric']} by "
                   f"{s['uplift_pct']:.1f}% ({s['incremental_trx']:+.0f} {t['metric']}, net value ${s['net_value']:,.0f}).")
    sm = (targeting or {}).get("summary") or {}
    if sm:
        out.append(f"The top {sm['high_volume_deciles']} deciles deliver {sm['top_rx_share_pct']:.0f}% of {t['metric']} but receive "
                   f"{sm['top_call_share_pct']:.0f}% of {t['primary_l']} (alignment score {sm['alignment_score_pct']:.0f}%).")
    if incentive:
        i = incentive["summary"]
        cos = f"{i['cost_of_sales_pct']:.2f}%" if i["cost_of_sales_pct"] is not None else "n/a"
        out.append(f"{i['pct_at_or_above_target']:.0f}% of territory-quarters reach quota; the plan pays "
                   f"{i['payout_vs_target_pct']:.0f}% of target incentive ({cos} of {t['metric']} revenue).")
    if kpi.get("trx_change_pct_6m") is not None:
        out.append(f"{t['metric']} volume is {kpi['trx_change_pct_6m']:+.1f}% over the latest 6 months vs the prior 6.")
    return out


def build_report(settings: Settings, f: an.Filters, budget_change_pct: float = 0.0) -> dict:
    profile = get_profile(settings)
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
        "profile": profile, "labels": tokens(profile),
        "targeting": targeting, "incentive": incentive,
        "filters": f.__dict__, "kpis": kpi,
        "trend": an.trend(settings, f), "regions": an.breakdown(settings, f, "region"),
        "specialties": an.breakdown(settings, f, "specialty"), "tiers": an.breakdown(settings, f, "tier"),
        "model": model, "roi": roi, "optimization": opt,
        "insights": insights(kpi, model, roi, opt, targeting, incentive, profile),
    }


__all__ = ["get_model", "get_roi", "get_optimization", "get_targeting", "get_incentive", "insights", "build_report", "ModelError"]
