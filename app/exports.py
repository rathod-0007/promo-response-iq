"""Excel workbook and PowerPoint deck built from a report dict, worded with the loaded data set's labels."""
from __future__ import annotations

import io
import re

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches, Pt

from .profile import tier_name

NAVY = "1F2A44"


def _safe_sheet(name: str, used: set) -> str:
    base = re.sub(r"[\[\]:*?/\\]", " ", name).strip()[:31] or "Sheet"
    out, n = base, 2
    while out.lower() in used:
        out = f"{base[:28]} {n}"
        n += 1
    used.add(out.lower())
    return out


def _sheet(wb: Workbook, used: set, title: str, df: pd.DataFrame) -> None:
    ws = wb.create_sheet(_safe_sheet(title, used))
    ws.append([str(c) for c in df.columns])
    for row in df.itertuples(index=False):
        ws.append([None if pd.isna(v) else (v.item() if hasattr(v, "item") else v) for v in row])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=NAVY)
        c.alignment = Alignment(horizontal="center")
    for i, col in enumerate(df.columns, 1):
        width = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(width, 40)
    ws.freeze_panes = "A2"


def _columns(report: dict) -> dict:
    """Source column name -> header shown to the reader."""
    t = report["labels"]
    return {"trx": t["metric"], "calls": t["primary"], "samples": t["second"], "emails": t["third"],
            "hcps": t["entities"], "hcp_id": f"{t['entity']} ID", "name": t["entity"], "month": "Month",
            "region": t["region"], "specialty": t["specialty"], "tier": t["tier"],
            "trx_per_call": f"{t['metric']} per {t['primary_unit']}"}


def _term_label(report: dict, term: str) -> str:
    t, p = report["labels"], report["profile"]
    if term.startswith("calls_tier_"):
        return f"{t['primary']} - {tier_name(p, term.rsplit('_', 1)[1])}"
    return {"samples": t["second"], "emails": t["third"]}.get(term, term)


def build_workbook(report: dict) -> bytes:
    t, p = report["labels"], report["profile"]
    cols = _columns(report)
    wb = Workbook()
    used: set = {"summary"}
    ws = wb.active
    ws.title = "Summary"
    ws.append(["RxLift - Executive Summary"])
    ws["A1"].font = Font(bold=True, size=14, color=NAVY)
    ws.append([f"Data set: {p['name']}"])
    ws.append([])
    kpi_names = {"total_trx": f"Total {t['metric']}", "total_calls": f"Total {t['primary']}",
                 "total_samples": f"Total {t['second']}", "total_emails": f"Total {t['third']}",
                 "active_hcps": f"Active {t['entities']}", "trx_per_call": cols["trx_per_call"],
                 "trx_change_pct_6m": f"{t['metric']} change % (latest 6M vs prior 6M)"}
    active = {c["key"] for c in p["channels"] if c["active"]}
    for k, v in report["kpis"].items():
        if k == "total_samples" and "samples" not in active or k == "total_emails" and "emails" not in active:
            continue
        ws.append([kpi_names.get(k, k.replace("_", " ").title()), v])
    ws.append([])
    ws.append(["Key insights"])
    ws.cell(ws.max_row, 1).font = Font(bold=True)
    for line in report["insights"]:
        ws.append([line])
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 18

    drop = [c for c in ("samples", "emails") if c not in active]
    _sheet(wb, used, "Monthly Trend", report["trend"].drop(columns=drop).rename(columns=cols))
    for key, df in (("region", report["regions"]), ("specialty", report["specialties"])):
        dim = next(d for d in p["dimensions"] if d["key"] == key)
        if dim["active"]:
            _sheet(wb, used, f"By {dim['label']}", df.rename(columns={"name": dim["label"]}).rename(columns=cols))
    terms = pd.DataFrame(report["model"].terms)
    terms["term"] = [_term_label(report, x) for x in terms["term"]]
    _sheet(wb, used, "Response Model", terms)
    roi = pd.DataFrame(report["roi"])
    roi["scope"] = [tier_name(p, s) if c == "calls" else s for c, s in zip(roi["channel"], roi["scope"])]
    roi["channel"] = [{"calls": t["primary"], "samples": t["second"], "emails": t["third"]}[c] for c in roi["channel"]]
    _sheet(wb, used, "Channel ROI", roi)
    opt = report["optimization"]
    by_tier = pd.DataFrame(opt["by_tier"]).rename(columns={"tier": t["tier"], "hcps": t["entities"]})
    _sheet(wb, used, f"Optimizer by {t['tier']}", by_tier)
    plan = opt["plan"].sort_values("delta_trx", ascending=False).rename(
        columns={**cols, "current_calls": f"current {t['primary_l']}", "recommended_calls": f"recommended {t['primary_l']}",
                 "delta_calls": f"change in {t['primary_l']}", "expected_trx_current": f"expected {t['metric']} now",
                 "expected_trx_new": f"expected {t['metric']} planned", "delta_trx": f"change in {t['metric']}"})
    _sheet(wb, used, f"{t['primary']} Plan", plan)
    tg = report.get("targeting") or {}
    if tg.get("deciles"):
        _sheet(wb, used, "Targeting Deciles", pd.DataFrame(tg["deciles"]).rename(columns={
            "trx": t["metric"], "calls": t["primary"], "rx_share_pct": f"{t['metric']} share %", "call_share_pct": f"{t['primary']} share %",
            "trx_per_call": cols["trx_per_call"], "hcps": t["entities"]}))
    if tg.get("segments"):
        _sheet(wb, used, "Segments", pd.DataFrame(tg["segments"]).rename(columns={
            "rx_share_pct": f"{t['metric']} share %", "call_share_pct": f"{t['primary']} share %",
            "calls_per_hcp": f"{t['primary']} per {t['entity']}", "hcps": t["entities"]}))
    ic = report.get("incentive")
    if ic:
        _sheet(wb, used, "IC By Quarter", pd.DataFrame(ic["by_quarter"]))
        _sheet(wb, used, f"IC {t['territory']} {ic['quarter']}", pd.DataFrame(ic["territories"]).rename(columns={"actual": t["metric"]}))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _title(slide, text: str) -> None:
    box = slide.shapes.title
    box.text = text
    for para in box.text_frame.paragraphs:
        for r in para.runs:
            r.font.size = Pt(28)
            r.font.bold = True
            r.font.color.rgb = RGBColor.from_string(NAVY)


def _bullets(slide, lines: list[str], size: int = 18) -> None:
    tf = slide.placeholders[1].text_frame
    tf.clear()
    for i, line in enumerate(lines):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.text = line
        para.font.size = Pt(size)


def build_deck(report: dict) -> bytes:
    t, p = report["labels"], report["profile"]
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    title_only, title_body = prs.slide_layouts[5], prs.slide_layouts[1]

    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = f"Promotion Response & {t['primary']} Allocation Review"
    s.placeholders[1].text = f"RxLift • {p['name']}"

    k = report["kpis"]
    s = prs.slides.add_slide(title_body)
    _title(s, "Performance at a glance")
    _bullets(s, [
        f"Total {t['metric']}: {k['total_trx']:,}   |   {t['primary']}: {k['total_calls']:,}   |   Active {t['entities']}: {k['active_hcps']:,}",
        f"{t['metric']} per {t['primary_unit']}: {k['trx_per_call']}" if k["trx_per_call"] is not None else f"{t['metric']} per {t['primary_unit']}: n/a",
        *report["insights"][:3],
    ])

    s = prs.slides.add_slide(title_only)
    _title(s, f"Monthly {t['metric']}")
    tr = report["trend"]
    cd = CategoryChartData()
    cd.categories = list(tr["month"])
    cd.add_series(t["metric"], [int(v) for v in tr["trx"]])
    s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(0.7), Inches(1.5), Inches(12), Inches(5.5), cd)

    s = prs.slides.add_slide(title_only)
    _title(s, f"{t['primary']} responsiveness by {t['entity']} {t['tier'].lower()} (elasticity)")
    cd = CategoryChartData()
    tiers = sorted(report["model"].tier_beta)
    cd.categories = [tier_name(p, x) for x in tiers]
    cd.add_series("Elasticity", [report["model"].tier_beta[x] for x in tiers])
    s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.7), Inches(1.5), Inches(12), Inches(5.5), cd)

    s = prs.slides.add_slide(title_body)
    sm = report["optimization"]["summary"]
    _title(s, f"Recommendation: reallocate {t['primary_l']}")
    _bullets(s, [
        f"Budget change: {report['optimization']['budget_change_pct']:+.0f}%  →  {sm['recommended_calls']} {t['primary_l']}/month "
        f"(from {sm['current_calls']})",
        f"Expected {t['metric']}: {sm['expected_trx']:,.0f} vs {sm['current_trx']:,.0f}  ({sm['uplift_pct']:+.1f}%)"
        if sm["uplift_pct"] is not None else f"Expected {t['metric']} uplift: n/a",
        f"Net value: ${sm['net_value']:,.0f} per month",
        f"Shift {t['primary_l']} from low-responsiveness to high-responsiveness {t['entities']}; see the Excel '{t['primary']} Plan' sheet for the list.",
    ])
    tg, ic = report.get("targeting") or {}, report.get("incentive")
    if tg.get("summary") or ic:
        s = prs.slides.add_slide(title_body)
        _title(s, "Targeting and incentive compensation")
        lines = []
        if tg.get("summary"):
            x = tg["summary"]
            lines.append(f"Top {x['high_volume_deciles']} deciles: {x['top_rx_share_pct']:.0f}% of {t['metric']}, "
                         f"{x['top_call_share_pct']:.0f}% of {t['primary_l']}; alignment score {x['alignment_score_pct']:.0f}%")
        if ic:
            i = ic["summary"]
            cos = f"{i['cost_of_sales_pct']:.2f}%" if i["cost_of_sales_pct"] is not None else "n/a"
            lines += [f"{i['pct_at_or_above_target']:.0f}% of {t['territory'].lower()}-quarters reach quota; "
                      f"{i['pct_below_threshold']:.0f}% fall below the payout threshold",
                      f"Plan pays {i['payout_vs_target_pct']:.0f}% of target incentive (${i['total_payout']:,.0f}); cost of sales {cos}"]
        _bullets(s, lines)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
