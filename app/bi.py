"""BI layer: stable, tool-friendly objects in PostgreSQL for Tableau, Power BI, Sisense (or any SQL/CSV tool).

* Star-schema VIEWS (bi_dim_*, bi_fact_*) are always current: they are rebuilt with every data load.
* Analysis TABLES (bi_model_*, bi_call_plan, bi_targeting_*, bi_ic_*) hold the results of the response model,
  optimizer, targeting and incentive engines at the default plan. They are re-published after every upload
  and on demand, so a BI dashboard sees exactly what the web app shows.
* Names and column names are stable; human wording (dataset-specific labels) lives in bi_dataset_labels.
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import make_url

from . import analytics as an
from . import service
from .config import Settings
from .db import data_version, get_engine, has_territories
from .incentive import IncentiveError, compute, resolve_plan
from .modeling import ModelError
from .profile import channel_label, get_profile, tier_name, tokens

VIEWS = ["bi_fact_hcp_month", "bi_flat_hcp_month", "bi_dim_hcp", "bi_dim_territory", "bi_dim_month"]
TABLES = {
    "bi_model_terms": "Response-model coefficients with 95% confidence intervals",
    "bi_channel_roi": "Incremental volume and ROI per channel (and tier for the main channel)",
    "bi_call_plan": "Optimizer: recommended main-channel activity per prescriber at the current budget",
    "bi_targeting_deciles": "Share of volume vs share of main-channel activity by prescriber decile",
    "bi_hcp_segment": "Prescriber decile and response-based segment (Invest / Defend / Develop / Self-serve)",
    "bi_ic_territory_quarter": "Incentive compensation: quota, attainment and payout per territory and quarter",
    "bi_ic_payout_curve": "Incentive payout curve (attainment % to payout %)",
    "bi_dataset_labels": "Wording of the loaded data set (metric, channels, dimensions)",
    "bi_refresh_log": "When the analysis tables were last published",
}


def _write(conn, name: str, df: pd.DataFrame) -> int:
    df.to_sql(name, conn, if_exists="replace", index=False)
    comment = TABLES[name].replace(chr(39), chr(39) * 2).replace("%", "%%")   # %% because exec_driver_sql treats % as a placeholder
    conn.exec_driver_sql(f'COMMENT ON TABLE "{name}" IS ' + chr(39) + comment + chr(39))
    return len(df)


def _frames(settings: Settings) -> tuple[dict, list[str]]:
    f = an.Filters()
    profile = get_profile(settings)
    t = tokens(profile)
    notes: list[str] = []
    frames: dict[str, pd.DataFrame] = {}

    labels = [("dataset_name", profile["name"]), ("dataset_kind", profile["kind"])]
    labels += [(f"label_{k}", v) for k, v in profile["labels"].items()]
    labels += [(f"channel_{c['key']}", c["label"]) for c in profile["channels"]]
    labels += [(f"channel_{c['key']}_active", str(c["active"]).lower()) for c in profile["channels"]]
    frames["bi_dataset_labels"] = pd.DataFrame(labels, columns=["label_key", "label_value"])

    try:
        model, _ = service.get_model(settings, f)
        terms = pd.DataFrame(model.terms).rename(columns={"term": "term_key", "coef": "coefficient", "t": "t_stat"})
        terms.insert(1, "term_label", [_term_label(profile, k) for k in terms["term_key"]])
        frames["bi_model_terms"] = terms
        roi = pd.DataFrame(service.get_roi(settings, f))
        roi = roi.rename(columns={"channel": "channel_key", "scope": "scope_value"})
        roi.insert(1, "channel_label", [channel_label(profile, k) for k in roi["channel_key"]])
        roi["scope_label"] = [tier_name(profile, s) if c == "calls" else s for c, s in zip(roi["channel_key"], roi["scope_value"])]
        frames["bi_channel_roi"] = roi
        opt = service.get_optimization(settings, f, 0.0)
        plan = opt["plan"][["hcp_id", "tier", "current_calls", "recommended_calls", "delta_calls",
                            "expected_trx_current", "expected_trx_new", "delta_trx"]]
        frames["bi_call_plan"] = plan
    except ModelError as e:
        notes.append(f"Model-based tables skipped: {e}")

    tg_beta = None
    try:
        tg_beta = service.get_model(settings, f)[0].tier_beta
    except ModelError:
        pass
    from . import targeting as tg
    res = tg.analyze(an.hcp_totals(settings, f), settings.targeting, tg_beta, t, include_hcp=True)
    if res["deciles"]:
        frames["bi_targeting_deciles"] = pd.DataFrame(res["deciles"]).rename(columns={"rx_share_pct": "trx_share_pct"})
        frames["bi_hcp_segment"] = res["hcp_segments"]

    if has_territories(settings):
        try:
            plan_ = resolve_plan(settings)
            first = compute(settings, plan_)
            rows = []
            for q in first["quarters"]:
                r = compute(settings, plan_, quarter=q)
                rows += [{"quarter": q, **row} for row in r["territories"]]
            ic = pd.DataFrame(rows).rename(columns={"actual": "trx"})
            frames["bi_ic_territory_quarter"] = ic
            frames["bi_ic_payout_curve"] = pd.DataFrame(first["curve"])
        except IncentiveError as e:
            notes.append(f"Incentive tables skipped: {e}")
    else:
        notes.append("Incentive tables skipped: no territory data loaded.")
    return frames, notes


def _term_label(profile: dict, key: str) -> str:
    t = tokens(profile)
    if key.startswith("calls_tier_"):
        return f"{t['primary']} - {tier_name(profile, key.rsplit('_', 1)[1])}"
    return {"samples": t["second"], "emails": t["third"]}.get(key, key)


def publish(settings: Settings) -> dict:
    """Recompute and publish all analysis tables atomically. Returns {table: rows} plus notes."""
    frames, notes = _frames(settings)
    now = datetime.now(timezone.utc)
    written: dict[str, int] = {}
    with get_engine(settings).begin() as conn:
        for name in TABLES:
            if name == "bi_refresh_log":
                continue
            if name in frames:
                written[name] = _write(conn, name, frames[name])
            else:  # stale results from a previous data set must not linger
                conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{name}"')
        written["bi_refresh_log"] = _write(conn, "bi_refresh_log", pd.DataFrame(
            [{"refreshed_at": now, "load_id": data_version(settings), "source": get_profile(settings)["source"],
              "tables_published": len(written), "notes": " | ".join(notes)}]))
    return {"published": written, "notes": notes, "refreshed_at": now.isoformat()}


def _published_load(settings: Settings):
    """Load id the BI tables were computed from (None when never published or published by an older version)."""
    with get_engine(settings).connect() as conn:
        has = conn.execute(text("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = :s "
                                "AND table_name = 'bi_refresh_log' AND column_name = 'load_id'"), {"s": settings.schema}).scalar()
        return conn.execute(text("SELECT load_id FROM bi_refresh_log LIMIT 1")).scalar() if has else None


def ensure_published(settings: Settings) -> None:
    """Publish on first start and after every data load, without ever blocking the app if it fails."""
    try:
        if _published_load(settings) != data_version(settings):
            publish(settings)
    except Exception:  # BI is a convenience layer: never block the app, but do not hide the reason
        logging.getLogger(__name__).exception("Could not publish the BI analysis tables")


def connection_info(settings: Settings) -> dict:
    url = make_url(settings.database_url)
    return {"driver": url.drivername.split("+")[0], "host": url.host, "port": url.port or 5432,
            "database": url.database, "schema": settings.schema, "user": url.username}


def catalog(settings: Settings) -> dict:
    """Objects a BI tool can use, with row counts, descriptions and columns (read live)."""
    with get_engine(settings).connect() as conn:
        rows = conn.execute(text("""
            SELECT c.relname AS name, c.relkind AS kind, obj_description(c.oid, 'pg_class') AS description
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :s AND c.relkind IN ('r', 'v') AND c.relname LIKE 'bi\\_%' ESCAPE '\\'
            ORDER BY c.relkind DESC, c.relname"""), {"s": settings.schema}).mappings().all()
        objs = []
        for r in rows:
            cols = conn.execute(text("SELECT column_name, data_type FROM information_schema.columns "
                                     "WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position"),
                                {"s": settings.schema, "t": r["name"]}).all()
            n = conn.execute(text(f'SELECT COUNT(*) FROM "{r["name"]}"')).scalar()
            objs.append({"name": r["name"], "kind": "view" if r["kind"] == "v" else "table", "description": r["description"] or "",
                         "rows": int(n), "columns": [{"name": c[0], "type": c[1]} for c in cols]})
        log = conn.execute(text("SELECT to_regclass('bi_refresh_log') IS NOT NULL")).scalar()
        refreshed = conn.execute(text("SELECT refreshed_at, notes FROM bi_refresh_log LIMIT 1")).mappings().first() if log else None
    return {"connection": connection_info(settings), "objects": objs,
            "refreshed_at": refreshed["refreshed_at"].isoformat() if refreshed else None,
            "notes": [n for n in (refreshed["notes"].split(" | ") if refreshed and refreshed["notes"] else [])]}


def export_dir(settings: Settings, folder) -> dict[str, int]:
    """Write every bi_* object as <name>.csv into `folder` (the data source of the Tableau and Power BI files)."""
    from pathlib import Path
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with get_engine(settings).connect() as conn:
        for o in catalog(settings)["objects"]:
            res = conn.execute(text(f'SELECT * FROM "{o["name"]}"'))
            with open(out / f"{o['name']}.csv", "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(res.keys())
                n = 0
                for row in res:
                    w.writerow(row)
                    n += 1
            counts[o["name"]] = n
    return counts


def csv_pack(settings: Settings) -> bytes:
    """ZIP of every bi_* object as CSV (for tools that import files: Tableau text file, Power BI Text/CSV, Sisense CSV)."""
    info = catalog(settings)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        with get_engine(settings).connect() as conn:
            for o in info["objects"]:
                res = conn.execute(text(f'SELECT * FROM "{o["name"]}"'))
                out = io.StringIO()
                w = csv.writer(out)
                w.writerow(res.keys())
                w.writerows(res)
                z.writestr(f"{o['name']}.csv", out.getvalue())
        lines = ["RxLift BI pack", f"Published: {info['refreshed_at'] or 'n/a'}", "",
                 "Load the *_fact_* / *_dim_* files as a star schema (join on hcp_id, territory_id, month_start/month_key).",
                 "Other files are ready-made analysis results. bi_dataset_labels holds the wording of this data set.", ""]
        lines += [f"{o['name']}.csv  ({o['rows']:,} rows): {o['description']}" for o in info["objects"]]
        z.writestr("README.txt", "\n".join(lines))
    return buf.getvalue()
