"""FastAPI app: JSON API + static dashboard."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import analytics as an
from . import exports, service
from .config import Settings, load_settings
from .db import ensure_db
from .modeling import ModelError

STATIC = Path(__file__).resolve().parent / "static"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _records(df):
    return df.astype(object).where(df.notna(), None).to_dict("records")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    ensure_db(settings)
    app = FastAPI(title="PromoResponseIQ", version="1.0.0")

    def filters(region: str | None = None, specialty: str | None = None, tier: str | None = None,
                start: str | None = None, end: str | None = None) -> an.Filters:
        meta = an.meta(settings)
        for name, val, allowed in (("region", region, meta["regions"]), ("specialty", specialty, meta["specialties"]),
                                   ("tier", tier, meta["tiers"])):
            if val and val not in allowed:
                raise HTTPException(422, f"Unknown {name}: {val}")
        for name, val in (("start", start), ("end", end)):
            if val and (len(val) != 7 or val[4] != "-" or not val[:4].isdigit() or not val[5:].isdigit()):
                raise HTTPException(422, f"{name} must be YYYY-MM")
        if start and end and start > end:
            raise HTTPException(422, "start must not be after end")
        return an.Filters(region or None, specialty or None, tier or None, start or None, end or None)

    def model_guard(fn):
        try:
            return fn()
        except ModelError as e:
            raise HTTPException(422, str(e))

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/meta")
    def meta():
        return {**an.meta(settings), "economics": settings.economics,
                "max_calls_per_hcp": settings.model["max_calls_per_hcp"]}

    @app.get("/api/kpis")
    def kpis(region: str | None = None, specialty: str | None = None, tier: str | None = None,
             start: str | None = None, end: str | None = None):
        return an.kpis(settings, filters(region, specialty, tier, start, end))

    @app.get("/api/trend")
    def trend(region: str | None = None, specialty: str | None = None, tier: str | None = None,
              start: str | None = None, end: str | None = None):
        return _records(an.trend(settings, filters(region, specialty, tier, start, end)))

    @app.get("/api/breakdown/{by}")
    def breakdown(by: str, region: str | None = None, specialty: str | None = None, tier: str | None = None,
                  start: str | None = None, end: str | None = None):
        if by not in an.DIMENSIONS:
            raise HTTPException(404, f"Unknown dimension: {by}")
        return _records(an.breakdown(settings, filters(region, specialty, tier, start, end), by))

    @app.get("/api/top-hcps")
    def top(limit: int = Query(15, ge=1, le=100), region: str | None = None, specialty: str | None = None,
            tier: str | None = None, start: str | None = None, end: str | None = None):
        return _records(an.top_hcps(settings, filters(region, specialty, tier, start, end), limit))

    @app.get("/api/model")
    def model(region: str | None = None, specialty: str | None = None, tier: str | None = None,
              start: str | None = None, end: str | None = None):
        f = filters(region, specialty, tier, start, end)
        m, _ = model_guard(lambda: service.get_model(settings, f))
        return {"model": m.to_dict(), "roi": service.get_roi(settings, f)}

    @app.get("/api/optimize")
    def optimize(budget_change_pct: float = Query(0.0, ge=-50, le=100), region: str | None = None,
                 specialty: str | None = None, tier: str | None = None, start: str | None = None,
                 end: str | None = None, plan_limit: int = Query(12, ge=1, le=200)):
        f = filters(region, specialty, tier, start, end)
        opt = model_guard(lambda: service.get_optimization(settings, f, budget_change_pct))
        plan = opt["plan"]
        movers = plan.reindex(plan["delta_trx"].abs().sort_values(ascending=False).index).head(plan_limit)
        return {"budget_change_pct": opt["budget_change_pct"], "summary": opt["summary"],
                "by_tier": opt["by_tier"], "top_moves": _records(movers)}

    @app.get("/api/insights")
    def insights(budget_change_pct: float = Query(0.0, ge=-50, le=100), region: str | None = None,
                 specialty: str | None = None, tier: str | None = None, start: str | None = None,
                 end: str | None = None):
        f = filters(region, specialty, tier, start, end)
        r = model_guard(lambda: service.build_report(settings, f, budget_change_pct))
        return {"insights": r["insights"]}

    def _export(kind, region, specialty, tier, start, end, budget_change_pct):
        f = filters(region, specialty, tier, start, end)
        r = model_guard(lambda: service.build_report(settings, f, budget_change_pct))
        if kind == "xlsx":
            return Response(exports.build_workbook(r), media_type=XLSX,
                            headers={"Content-Disposition": 'attachment; filename="promo_response_report.xlsx"'})
        return Response(exports.build_deck(r), media_type=PPTX,
                        headers={"Content-Disposition": 'attachment; filename="promo_response_review.pptx"'})

    @app.get("/api/export/xlsx")
    def export_xlsx(budget_change_pct: float = Query(0.0, ge=-50, le=100), region: str | None = None,
                    specialty: str | None = None, tier: str | None = None, start: str | None = None,
                    end: str | None = None):
        return _export("xlsx", region, specialty, tier, start, end, budget_change_pct)

    @app.get("/api/export/pptx")
    def export_pptx(budget_change_pct: float = Query(0.0, ge=-50, le=100), region: str | None = None,
                    specialty: str | None = None, tier: str | None = None, start: str | None = None,
                    end: str | None = None):
        return _export("pptx", region, specialty, tier, start, end, budget_change_pct)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app


app = None


def get_app() -> FastAPI:
    global app
    if app is None:
        app = create_app()
    return app
