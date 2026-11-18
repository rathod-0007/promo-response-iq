"""Excel workbook and PowerPoint deck built from a report dict."""
from __future__ import annotations

import io

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches, Pt

NAVY = "1F2A44"


def _sheet(wb: Workbook, title: str, df: pd.DataFrame) -> None:
    ws = wb.create_sheet(title)
    ws.append(list(df.columns))
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


def build_workbook(report: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["PromoResponseIQ - Executive Summary"])
    ws["A1"].font = Font(bold=True, size=14, color=NAVY)
    ws.append([])
    for k, v in report["kpis"].items():
        ws.append([k.replace("_", " ").title(), v])
    ws.append([])
    ws.append(["Key insights"])
    ws.cell(ws.max_row, 1).font = Font(bold=True)
    for line in report["insights"]:
        ws.append([line])
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 18
    _sheet(wb, "Monthly Trend", report["trend"])
    _sheet(wb, "Regions", report["regions"])
    _sheet(wb, "Specialties", report["specialties"])
    _sheet(wb, "Response Model", pd.DataFrame(report["model"].terms))
    _sheet(wb, "Channel ROI", pd.DataFrame(report["roi"]))
    opt = report["optimization"]
    _sheet(wb, "Optimizer By Tier", pd.DataFrame(opt["by_tier"]))
    _sheet(wb, "Call Plan", opt["plan"].sort_values("delta_trx", ascending=False))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _title(slide, text: str) -> None:
    box = slide.shapes.title
    box.text = text
    for p in box.text_frame.paragraphs:
        for r in p.runs:
            r.font.size = Pt(28)
            r.font.bold = True
            r.font.color.rgb = RGBColor.from_string(NAVY)


def _bullets(slide, lines: list[str], size: int = 18) -> None:
    body = slide.placeholders[1]
    tf = body.text_frame
    tf.clear()
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.font.size = Pt(size)


def build_deck(report: dict) -> bytes:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    title_only, title_body = prs.slide_layouts[5], prs.slide_layouts[1]

    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = "Promotion Response & Call Allocation Review"
    s.placeholders[1].text = "PromoResponseIQ • generated from the live analytics warehouse"

    k = report["kpis"]
    s = prs.slides.add_slide(title_body)
    _title(s, "Performance at a glance")
    _bullets(s, [
        f"Total Rx: {k['total_trx']:,}   |   Calls: {k['total_calls']:,}   |   Active HCPs: {k['active_hcps']:,}",
        f"Rx per call: {k['trx_per_call']}" if k["trx_per_call"] is not None else "Rx per call: n/a",
        *report["insights"][:3],
    ])

    s = prs.slides.add_slide(title_only)
    _title(s, "Monthly Rx vs calls")
    tr = report["trend"]
    cd = CategoryChartData()
    cd.categories = list(tr["month"])
    cd.add_series("Rx", [int(v) for v in tr["trx"]])
    s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(0.7), Inches(1.5), Inches(12), Inches(5.5), cd)

    s = prs.slides.add_slide(title_only)
    _title(s, "Call responsiveness by HCP tier (elasticity)")
    cd = CategoryChartData()
    tiers = sorted(report["model"].tier_beta)
    cd.categories = [f"Tier {t}" for t in tiers]
    cd.add_series("Elasticity", [report["model"].tier_beta[t] for t in tiers])
    s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.7), Inches(1.5), Inches(12), Inches(5.5), cd)

    s = prs.slides.add_slide(title_body)
    sm = report["optimization"]["summary"]
    _title(s, "Recommendation: reallocate calls")
    _bullets(s, [
        f"Budget change: {report['optimization']['budget_change_pct']:+.0f}%  →  {sm['recommended_calls']} calls/month "
        f"(from {sm['current_calls']})",
        f"Expected Rx: {sm['expected_trx']:,.0f} vs {sm['current_trx']:,.0f}  ({sm['uplift_pct']:+.1f}%)"
        if sm["uplift_pct"] is not None else "Expected Rx uplift: n/a",
        f"Net value: ${sm['net_value']:,.0f} per month",
        "Shift calls from low-responsiveness HCPs to high-responsiveness HCPs; see Excel 'Call Plan' for the HCP list.",
    ])
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
