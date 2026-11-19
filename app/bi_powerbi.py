"""Generate the Power BI project (PBIP: TMDL semantic model + PBIR report) from whatever data set is loaded.

The model reads the BI tables as CSV files from a Data folder (parameter `DataFolder`; edit it under Transform data >
Edit parameters if you move the folder), so no database login is needed. To read PostgreSQL live instead, point the
table queries at the `bi_*` views. Names, titles and which pages appear follow the loaded data set: labels come from
bi_dataset_labels, and a chart is only built when its columns exist and carry more than one value.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path

import pandas as pd

from . import bi
from .config import ROOT, Settings

OUT = ROOT / "bi" / "powerbi"
NAME = "PromoResponseIQ"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
V_REPORT, V_PAGE, V_PAGES, V_VERSION, V_VISUAL = "3.3.0", "2.1.0", "1.1.0", "1.0.0", "2.14.0"
SKIP_TABLES = {"bi_flat_hcp_month", "bi_refresh_log"}      # the flat table duplicates the star schema
ID_LIKE = {"year", "quarter", "decile", "hcp_id", "territory_id", "load_id"}
T = "\t"


def gid(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"promoresponseiq/{seed}"))


def vid(seed: str) -> str:
    return hashlib.sha1(seed.encode()).hexdigest()[:20]


def tmdl_name(name: str) -> str:
    return name if name.replace("_", "").isalnum() and not name[0].isdigit() else "'" + name.replace("'", "''") + "'"


def clean(text: str) -> str:
    return str(text).replace("'", "").replace('"', "").replace("[", "(").replace("]", ")")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------ semantic model
class Table:
    def __init__(self, name: str, df: pd.DataFrame):
        self.name, self.df = name, df
        self.cols: dict[str, dict] = {}
        for c in df.columns:
            s = df[c]
            if pd.api.types.is_integer_dtype(s):
                kind = "int"
            elif pd.api.types.is_float_dtype(s):
                kind = "num"
            elif c.endswith("_start"):
                kind = "date"
            else:
                kind = "text"
            self.cols[c] = {"kind": kind}
        self.measures: list[tuple[str, str, str]] = []     # name, DAX, format

    def distinct(self, col: str) -> int:
        return int(self.df[col].nunique())

    def tmdl(self) -> str:
        n = tmdl_name(self.name)
        out = [f"table {n}", f"{T}lineageTag: {gid('table/' + self.name)}", ""]
        for mname, dax, fmt in self.measures:
            out += [f"{T}measure {tmdl_name(mname)} = {dax}", f"{T}{T}formatString: {fmt}", f"{T}{T}lineageTag: {gid('measure/' + self.name + mname)}", ""]
        for c, f in self.cols.items():
            kind = f["kind"]
            dtype = {"int": "int64", "num": "double", "date": "dateTime", "text": "string"}[kind]
            summarize = "sum" if kind in ("int", "num") and not (c.endswith("_id") or c in ID_LIKE) else "none"
            lines = [f"{T}column {tmdl_name(c)}", f"{T}{T}dataType: {dtype}"]
            if c.endswith("_id") or c in ("month_key",):
                lines.append(f"{T}{T}isHidden")
            if kind == "date":
                lines.append(f"{T}{T}formatString: yyyy-mm-dd")
            elif kind == "int":
                lines.append(f"{T}{T}formatString: 0")
            lines += [f"{T}{T}lineageTag: {gid('column/' + self.name + c)}", f"{T}{T}summarizeBy: {summarize}", f"{T}{T}sourceColumn: {c}", ""]
            out += lines
        mtypes = {"int": "Int64.Type", "num": "type number", "date": "type date", "text": "type text"}
        typed = ", ".join('{"%s", %s}' % (c, mtypes[f["kind"]]) for c, f in self.cols.items())
        ind = T * 4
        out += [
            f"{T}partition {n} = m", f"{T}{T}mode: import", f"{T}{T}source =",
            f"{ind}let",
            f'{ind}    Source = Csv.Document(File.Contents(DataFolder & "{self.name}.csv"), [Delimiter=",", Columns={len(self.cols)}, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
            f"{ind}    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
            f'{ind}    Typed = Table.TransformColumnTypes(Promoted, {{{typed}}}, "en-US")',
            f"{ind}in", f"{ind}    Typed", "",
            f"{T}annotation PBI_ResultType = Table", "",
        ]
        return "\n".join(out)


def build_model(tables: dict[str, Table], data_dir: Path, out: Path, data_folder: str | None = None) -> list[tuple[str, str, str, str]]:
    model = out / f"{NAME}.SemanticModel"
    d = model / "definition"
    write_json(model / "definition.pbism", {"version": "4.2", "settings": {}})
    write_json(model / ".platform", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "SemanticModel", "displayName": NAME}, "config": {"version": "2.0", "logicalId": gid("semanticmodel")}})
    d.mkdir(parents=True, exist_ok=True)
    (d / "database.tmdl").write_text(f"database {NAME}\n{T}compatibilityLevel: 1600\n", encoding="utf-8")
    refs = "\n".join(f"ref table {tmdl_name(n)}" for n in tables)
    (d / "model.tmdl").write_text(
        f"model Model\n{T}culture: en-US\n{T}defaultPowerBIDataSourceVersion: powerBI_V3\n{T}discourageImplicitMeasures\n\n{refs}\nref expression DataFolder\n", encoding="utf-8")
    folder = data_folder or str(data_dir.resolve()) + "\\"
    (d / "expressions.tmdl").write_text(
        f'expression DataFolder = "{folder}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
        f"{T}lineageTag: {gid('param/DataFolder')}\n\n{T}annotation PBI_ResultType = Text\n", encoding="utf-8")
    for t in tables.values():
        (d / "tables").mkdir(exist_ok=True)
        (d / "tables" / f"{t.name}.tmdl").write_text(t.tmdl(), encoding="utf-8")
    # relationships: every table that carries a dimension's key points to that dimension (many -> one)
    dims = {n: t for n, t in tables.items() if n.startswith("bi_dim_")}
    key_of = {n: next(iter(t.cols)) for n, t in dims.items()}      # first column of a dimension is its key
    rels = []
    for n, t in tables.items():
        for dn, key in key_of.items():
            if dn != n and key in t.cols and t.cols[key]["kind"] == dims[dn].cols[key]["kind"]:
                if n.startswith("bi_dim_") and not (n == "bi_dim_hcp" and dn == "bi_dim_territory"):
                    continue                                    # only hcp -> territory among dimensions
                rels.append((n, key, dn, key))
    lines = []
    for fn, fc, tn, tc in rels:
        lines += [f"relationship {gid(f'rel/{fn}.{fc}->{tn}.{tc}')}", f"{T}fromColumn: {tmdl_name(fn)}.{tmdl_name(fc)}", f"{T}toColumn: {tmdl_name(tn)}.{tmdl_name(tc)}", ""]
    (d / "relationships.tmdl").write_text("\n".join(lines), encoding="utf-8")
    return rels


# ------------------------------------------------------------------ report (PBIR)
def column(entity, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def measure(entity, prop):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def agg(entity, prop, fn):
    return {"Aggregation": {"Expression": column(entity, prop), "Function": fn}}


def projection(kind, entity, prop, fn=None, active=False):
    if kind == "column":
        field, ref = column(entity, prop), f"{entity}.{prop}"
    elif kind == "measure":
        field, ref = measure(entity, prop), f"{entity}.{prop}"
    else:
        field, ref = agg(entity, prop, fn), f"{'Sum' if fn == 0 else 'Average'}({entity}.{prop})"
    p = {"field": field, "queryRef": ref, "nativeQueryRef": prop if kind != "agg" else f"{'Sum' if fn == 0 else 'Average'} of {prop}"}
    if active:
        p["active"] = True
    return p


def literal(text: str) -> dict:
    return {"expr": {"Literal": {"Value": "'" + str(text).replace("'", "''") + "'"}}}


class Page:
    def __init__(self, key: str, title: str):
        self.key, self.title, self.visuals = key, title, []

    def add(self, vtype: str, x: int, y: int, w: int, h: int, roles: dict, title: str | None = None, objects: dict | None = None):
        n = len(self.visuals)
        visual = {"visualType": vtype, "query": {"queryState": {r: {"projections": p} for r, p in roles.items()}}, "drillFilterOtherVisuals": True}
        if title:
            visual["visualContainerObjects"] = {"title": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}, "text": literal(title)}}]}
        if objects:
            visual["objects"] = objects
        self.visuals.append({
            "$schema": f"{SCHEMA}/visualContainer/{V_VISUAL}/schema.json", "name": vid(f"{self.key}/{n}/{vtype}/{title}"),
            "position": {"x": x, "y": y, "z": 1000 + n, "height": h, "width": w, "tabOrder": 1000 + n}, "visual": visual})


DROPDOWN = {"data": [{"properties": {"mode": literal("Dropdown")}}]}


def build_report(tables: dict[str, Table], labels: dict, out: Path) -> list[Page]:
    metric, entities = labels.get("label_metric", "Volume"), labels.get("label_entities", "Prescribers")
    primary, second, third = labels.get("channel_calls", "Activity"), labels.get("channel_samples", "Second channel"), labels.get("channel_emails", "Third channel")
    unit = primary.lower()
    if unit.endswith("s") and not unit.endswith("ss"):
        unit = unit[:-1]                                  # "detail visits" -> "detail visit"
    fact, dim_hcp, dim_month = tables.get("bi_fact_hcp_month"), tables.get("bi_dim_hcp"), tables.get("bi_dim_month")
    pages: list[Page] = []

    if fact and dim_hcp and dim_month:
        total, calls = f"Total {clean(metric)}", f"Total {clean(primary)}"
        fact.measures += [(total, "SUM(bi_fact_hcp_month[trx])", "#,0"), (calls, "SUM(bi_fact_hcp_month[calls])", "#,0"),
                          (f"{clean(metric)} per {clean(unit)}", f"DIVIDE([{total}], [{calls}])", "0.00"),
                          (f"Active {clean(entities)}", "DISTINCTCOUNT(bi_fact_hcp_month[hcp_id])", "#,0")]
        for key, lab, col in (("samples", second, "samples"), ("emails", third, "emails")):
            if labels.get(f"channel_{key}_active") == "true":
                fact.measures.append((f"Total {clean(lab)}", f"SUM(bi_fact_hcp_month[{col}])", "#,0"))
        p = Page("performance", "Performance")
        names = [m[0] for m in fact.measures]
        x, w = 20, (1280 - 40 - 15 * (len(names) - 1)) // len(names)
        for m in names:
            p.add("card", x, 20, w, 100, {"Values": [projection("measure", "bi_fact_hcp_month", m)]})
            x += w + 15
        p.add("lineChart", 20, 135, 800, 290, {"Category": [projection("column", "bi_dim_month", "month_start")],
                                               "Y": [projection("measure", "bi_fact_hcp_month", total)]}, f"{metric} by month")
        slicers = [d for d in ("region", "specialty", "tier") if d in dim_hcp.cols and dim_hcp.distinct(d) > 1]
        y = 135
        for d in slicers:
            p.add("slicer", 835, y, 425, 56, {"Values": [projection("column", "bi_dim_hcp", d, active=True)]}, labels.get(f"label_{d}", d.title()), DROPDOWN)
            y += 66
        bars = [d for d in ("region", "tier", "specialty") if d in slicers][:2]
        for i, d in enumerate(bars):
            wide = 620 if len(bars) > 1 else 1240
            p.add("clusteredColumnChart", 20 + i * 640, 440, wide, 260, {"Category": [projection("column", "bi_dim_hcp", d)],
                                                                         "Y": [projection("measure", "bi_fact_hcp_month", total)]},
                  f"{metric} by {labels.get(f'label_{d}', d).lower()}")
        pages.append(p)

    roi, dec, seg = tables.get("bi_channel_roi"), tables.get("bi_targeting_deciles"), tables.get("bi_hcp_segment")
    if roi is not None or dec is not None:
        p = Page("focus", "Where to focus")
        if roi is not None and len(roi.df):
            p.add("clusteredBarChart", 20, 20, 620, 330, {"Category": [projection("column", "bi_channel_roi", "scope_label")],
                                                          "Y": [projection("agg", "bi_channel_roi", "roi", 0)],
                                                          "Series": [projection("column", "bi_channel_roi", "channel_label")]},
                  "ROI by channel (x per $ spent)")
        if dec is not None and len(dec.df):
            p.add("clusteredColumnChart", 660, 20, 600, 330, {"Category": [projection("column", "bi_targeting_deciles", "decile")],
                                                              "Y": [projection("agg", "bi_targeting_deciles", "trx_share_pct", 0), projection("agg", "bi_targeting_deciles", "call_share_pct", 0)]},
                  f"Share of {metric} vs share of {primary.lower()} by decile")
            p.add("clusteredColumnChart", 20, 370, 620, 330, {"Category": [projection("column", "bi_targeting_deciles", "decile")],
                                                                                         "Y": [projection("agg", "bi_targeting_deciles", "call_index", 1)]},
                  f"{primary} index by decile (1.0 = proportional to {metric})")
        if seg is not None and len(seg.df) and "segment" in seg.cols:
            p.add("clusteredBarChart", 660, 370, 600, 330, {"Category": [projection("column", "bi_hcp_segment", "segment")],
                                                            "Y": [projection("agg", "bi_hcp_segment", "trx", 0)]}, f"{metric} by response-based segment")
        pages.append(p)

    ic, curve = tables.get("bi_ic_territory_quarter"), tables.get("bi_ic_payout_curve")
    if ic is not None and len(ic.df):
        p = Page("incentive", "Incentive plan")
        p.add("slicer", 20, 20, 300, 56, {"Values": [projection("column", "bi_ic_territory_quarter", "quarter", active=True)]}, "Quarter", DROPDOWN)
        p.add("clusteredColumnChart", 20, 90, 620, 300, {"Category": [projection("column", "bi_ic_territory_quarter", "territory")],
                                                          "Y": [projection("agg", "bi_ic_territory_quarter", "attainment_pct", 1)]}, "Quota attainment by territory (%)")
        p.add("clusteredColumnChart", 660, 90, 600, 300, {"Category": [projection("column", "bi_ic_territory_quarter", "territory")],
                                                           "Y": [projection("agg", "bi_ic_territory_quarter", "payout", 0)]}, "Incentive payout by territory ($)")
        if curve is not None and len(curve.df):
            p.add("lineChart", 20, 410, 620, 290, {"Category": [projection("column", "bi_ic_payout_curve", "attainment_pct")],
                                                   "Y": [projection("agg", "bi_ic_payout_curve", "payout_pct", 0)]}, "Payout curve (% of target incentive)")
        pages.append(p)

    rep = out / f"{NAME}.Report"
    write_json(rep / "definition.pbir", {"version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
    write_json(rep / ".platform", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Report", "displayName": NAME}, "config": {"version": "2.0", "logicalId": gid("report")}})
    d = rep / "definition"
    write_json(d / "version.json", {"$schema": f"{SCHEMA}/versionMetadata/{V_VERSION}/schema.json", "version": "2.0.0"})
    write_json(d / "report.json", {"$schema": f"{SCHEMA}/report/{V_REPORT}/schema.json", "themeCollection": {}})
    page_ids = [vid("page/" + p.key) for p in pages]
    write_json(d / "pages" / "pages.json", {"$schema": f"{SCHEMA}/pagesMetadata/{V_PAGES}/schema.json", "pageOrder": page_ids, "activePageName": page_ids[0]})
    for pid, p in zip(page_ids, pages):
        write_json(d / "pages" / pid / "page.json", {"$schema": f"{SCHEMA}/page/{V_PAGE}/schema.json", "name": pid, "displayName": p.title,
                                                       "displayOption": "FitToPage", "height": 720, "width": 1280})
        for v in p.visuals:
            write_json(d / "pages" / pid / "visuals" / v["name"] / "visual.json", v)
    return pages


def generate(settings: Settings, out: Path | None = None, data_folder: str | None = None) -> dict:
    """Write the .pbip project and its Data folder into `out`. `data_folder` overrides the DataFolder parameter's value
    (default: the Data folder next to the project, as an absolute path)."""
    out = Path(out or OUT)
    data = out / "Data"
    for p in (data, out / f"{NAME}.SemanticModel", out / f"{NAME}.Report"):
        if p.exists():
            shutil.rmtree(p)
    counts = bi.export_dir(settings, data)
    tables = {f.stem: Table(f.stem, pd.read_csv(f)) for f in sorted(data.glob("*.csv")) if f.stem not in SKIP_TABLES and f.stem != "bi_dataset_labels"}
    lab = pd.read_csv(data / "bi_dataset_labels.csv")
    labels = dict(zip(lab["label_key"], lab["label_value"].astype(str)))
    pages = build_report(tables, labels, out)           # adds the measures to the fact table
    rels = build_model(tables, data, out, data_folder)
    write_json(out / f"{NAME}.pbip", {"version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}], "settings": {"enableAutoRecovery": True}})
    return {"project": out / f"{NAME}.pbip", "tables": len(tables), "relationships": len(rels), "pages": len(pages),
            "visuals": sum(len(pg.visuals) for pg in pages), "exported": len(counts)}


DEFAULT_DATA_FOLDER = "C:\\PromoResponseIQ\\Data\\"
README = (
    "Promo Response IQ - Power BI project\r\n\r\n"
    "1. Unzip this folder (keep the layout), e.g. to C:\\PromoResponseIQ\r\n"
    "2. Open PromoResponseIQ.pbip in Power BI Desktop (free).\r\n"
    "3. If you unzipped somewhere else: Home > Transform data > Edit parameters > DataFolder = the full path of the Data folder, ending in a backslash.\r\n"
    "4. Home > Refresh.\r\n"
)


def package_bytes(settings: Settings, data_folder: str = DEFAULT_DATA_FOLDER) -> bytes:
    """The project as a zip (built in a throw-away folder), with DataFolder preset to `data_folder`."""
    import io
    import tempfile
    import zipfile
    with tempfile.TemporaryDirectory(prefix="pri_powerbi_") as tmp:
        generate(settings, Path(tmp), data_folder)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("README.txt", README)
            for f in sorted(Path(tmp).rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(tmp).as_posix())
        return buf.getvalue()
