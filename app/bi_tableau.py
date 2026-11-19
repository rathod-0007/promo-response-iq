"""Generate the Tableau workbook (.twb / .twbx with .hyper extracts) from whatever data set is loaded.

The BI tables (see bi.py) are packaged as Tableau extracts (.hyper, made with Tableau's official Hyper API), so the
workbook opens in Tableau Public (free; it only accepts extracts) as well as Tableau Desktop, with no database login.
Titles, field names and which charts appear follow the loaded data set: labels come from bi_dataset_labels, and a chart
is only built when its columns exist and carry more than one value.

Needs the optional dependency in requirements-bi.txt (tableauhyperapi).
"""
from __future__ import annotations

import datetime as dt
import shutil
import uuid
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import pandas as pd
from tableauhyperapi import Connection, CreateMode, Date, HyperProcess, Inserter, SqlType, TableDefinition, TableName, Telemetry

from . import bi
from .config import ROOT, Settings

OUT = ROOT / "bi" / "tableau"
WORKBOOK = "RxLift"
VERSION = "18.1"
BUILD = "2025.1.0 (20251.25.0414.1202)"
ID_LIKE = {"year", "quarter", "decile", "load_id", "tables_published"}
NL = chr(10)


def q(text) -> str:
    return quoteattr(str(text))


# ------------------------------------------------------------------ data sources (extracts)
class Source:
    """One BI table as a Tableau extract data source."""

    REMOTE = {"integer": 20, "real": 5, "string": 129, "date": 133}

    def __init__(self, name: str, df: pd.DataFrame, dbname: str):
        self.name, self.df, self.dbname = name, df, dbname
        self.ds = f"federated.{uuid.uuid4().hex[:28]}"
        self.fields: dict[str, dict] = {}
        for i, col in enumerate(df.columns):
            s = df[col]
            if pd.api.types.is_integer_dtype(s):
                idlike = col.endswith("_id") or col in ID_LIKE
                dtype, role, typ = "integer", ("dimension" if idlike else "measure"), ("ordinal" if idlike else "quantitative")
            elif pd.api.types.is_float_dtype(s):
                dtype, role, typ = "real", "measure", "quantitative"
            elif col.endswith("_start"):
                dtype, role, typ = "date", "dimension", "ordinal"
            else:
                dtype, role, typ = "string", "dimension", "nominal"
            self.fields[col] = {"datatype": dtype, "role": role, "type": typ, "ordinal": i}

    def has(self, col: str) -> bool:
        return col in self.fields

    def distinct(self, col: str) -> int:
        return int(self.df[col].nunique())

    def write_hyper(self, path: Path) -> None:
        """Create the extract file: one table, Extract.Extract, as Tableau expects."""
        sql = {"integer": SqlType.big_int(), "real": SqlType.double(), "string": SqlType.text(), "date": SqlType.date()}
        cols = [TableDefinition.Column(c, sql[f["datatype"]]) for c, f in self.fields.items()]
        table = TableDefinition(TableName("Extract", "Extract"), cols)
        path.parent.mkdir(parents=True, exist_ok=True)
        with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
            with Connection(hyper.endpoint, str(path), CreateMode.CREATE_AND_REPLACE) as conn:
                conn.catalog.create_schema("Extract")
                conn.catalog.create_table(table)
                with Inserter(conn, table) as ins:
                    for row in self.df.itertuples(index=False):
                        vals = []
                        for (c, f), v in zip(self.fields.items(), row):
                            if pd.isna(v):
                                vals.append(None)
                            elif f["datatype"] == "date":
                                d = pd.Timestamp(v)
                                vals.append(Date(d.year, d.month, d.day))
                            elif f["datatype"] == "integer":
                                vals.append(int(v))
                            elif f["datatype"] == "real":
                                vals.append(float(v))
                            else:
                                vals.append(str(v))
                        ins.add_row(vals)
                    ins.execute()

    def _records(self) -> str:
        out = []
        for c, f in self.fields.items():
            agg = "Sum" if f["role"] == "measure" else "Count"
            width = f"          <scale>1</scale>{NL}          <width>1073741823</width>{NL}" if f["datatype"] == "string" else ""
            out.append(f"""        <metadata-record class='column'>
          <remote-name>{escape(c)}</remote-name>
          <remote-type>{self.REMOTE[f['datatype']]}</remote-type>
          <local-name>[{escape(c)}]</local-name>
          <parent-name>[Extract]</parent-name>
          <remote-alias>{escape(c)}</remote-alias>
          <ordinal>{f['ordinal']}</ordinal>
          <local-type>{f['datatype']}</local-type>
          <aggregation>{agg}</aggregation>
{width}          <contains-null>true</contains-null>
        </metadata-record>""")
        return NL.join(out)

    def xml(self) -> str:
        conn = f"hyper.{uuid.uuid4().hex[:28]}"
        stamp = dt.datetime.now().strftime("%m/%d/%Y %I:%M:%S %p")
        overrides = NL.join(
            f"      <column datatype={q(f['datatype'])} name={q('[' + c + ']')} role={q(f['role'])} type={q(f['type'])} />"
            for c, f in self.fields.items())
        recs = self._records()
        return f"""    <datasource caption={q(self.name)} inline='true' name={q(self.ds)} version={q(VERSION)}>
      <connection class='federated'>
        <named-connections>
          <named-connection caption={q(self.name)} name={q(conn)}>
            <connection authentication='auth-none' class='hyper' dbname={q(self.dbname)} default-settings='yes' schema='Extract' sslmode='' username='tableau_internal_user' />
          </named-connection>
        </named-connections>
        <relation connection={q(conn)} name='Extract' table='[Extract].[Extract]' type='table' />
        <metadata-records>
{recs}
        </metadata-records>
      </connection>
      <aliases enabled='yes' />
{overrides}
      <extract count='-1' enabled='true' units='records'>
        <connection access_mode='readonly' authentication='auth-none' author-locale='en_US' class='hyper' dbname={q(self.dbname)} default-settings='yes' schema='Extract' sslmode='' tablename='Extract' update-time={q(stamp)} username='tableau_internal_user'>
          <relation name='Extract' table='[Extract].[Extract]' type='table' />
          <metadata-records>
{recs}
          </metadata-records>
        </connection>
      </extract>
    </datasource>"""


# ------------------------------------------------------------------ worksheets
class Sheet:
    """A one- or two-field chart: a measure on rows, a dimension on columns, optional colour dimension."""

    def __init__(self, name, src: Source, mark, dim, measure, agg="Sum", color=None, month=False, title=None):
        self.name, self.src, self.mark, self.dim, self.measure, self.agg = name, src, mark, dim, measure, agg
        self.color, self.month, self.title = color, month, title or name

    def instances(self):
        s, out = self.src, []
        if self.month:
            out.append((self.dim, "Month-Trunc", f"[tmn:{self.dim}:qk]", "quantitative"))
        else:
            suffix, typ = ("ok", "ordinal") if s.fields[self.dim]["type"] == "ordinal" else ("nk", "nominal")
            out.append((self.dim, "None", f"[none:{self.dim}:{suffix}]", typ))
        short = {"Sum": "sum", "Avg": "avg"}[self.agg]
        out.append((self.measure, self.agg, f"[{short}:{self.measure}:qk]", "quantitative"))
        if self.color:
            suffix, typ = ("ok", "ordinal") if s.fields[self.color]["type"] == "ordinal" else ("nk", "nominal")
            out.append((self.color, "None", f"[none:{self.color}:{suffix}]", typ))
        return out

    def xml(self) -> str:
        s, ds = self.src, self.src.ds
        inst = self.instances()
        used = sorted({c for c, *_ in inst})
        cols = NL.join(f"            <column datatype={q(s.fields[c]['datatype'])} name={q('[' + c + ']')} role={q(s.fields[c]['role'])} type={q(s.fields[c]['type'])} />" for c in used)
        ci = NL.join(f"            <column-instance column={q('[' + c + ']')} derivation={q(d)} name={q(n)} pivot='key' type={q(t)} />" for c, d, n, t in inst)
        enc = f"{NL}            <encodings>{NL}              <color column={q(f'[{ds}].' + inst[2][2])} />{NL}            </encodings>" if self.color else ""
        return f"""    <worksheet name={q(self.name)}>
      <layout-options>
        <title>
          <formatted-text>
            <run bold='true' fontsize='12'>{escape(self.title)}</run>
          </formatted-text>
        </title>
      </layout-options>
      <table>
        <view>
          <datasources>
            <datasource caption={q(s.name)} name={q(ds)} />
          </datasources>
          <datasource-dependencies datasource={q(ds)}>
{cols}
{ci}
          </datasource-dependencies>
          <aggregation value='true' />
        </view>
        <style />
        <panes>
          <pane selection-relaxation-option='selection-relaxation-allow'>
            <view>
              <breakdown value='auto' />
            </view>
            <mark class={q(self.mark)} />{enc}
          </pane>
        </panes>
        <rows>[{ds}].{inst[1][2]}</rows>
        <cols>[{ds}].{inst[0][2]}</cols>
      </table>
    </worksheet>"""

    def window(self, maximized: bool = False) -> str:
        flag = " maximized='true'" if maximized else ""
        return f"""    <window class='worksheet'{flag} name={q(self.name)}>
      <cards>
        <edge name='left'>
          <strip size='160'>
            <card type='pages' />
            <card type='filters' />
            <card type='marks' />
          </strip>
        </edge>
        <edge name='top'>
          <strip size='2147483647'>
            <card type='columns' />
          </strip>
          <strip size='2147483647'>
            <card type='rows' />
          </strip>
          <strip size='31'>
            <card type='title' />
          </strip>
        </edge>
      </cards>
    </window>"""


def dashboard(name: str, sheets: list[Sheet], columns: int = 2, width: int = 1280, height: int = 820) -> tuple[str, str]:
    rows = -(-len(sheets) // columns)
    zid, zones = 10, []
    for i, sh in enumerate(sheets):
        r, c = divmod(i, columns)
        in_row = min(columns, len(sheets) - r * columns)
        w = 100000 // in_row
        zid += 1
        zones.append(f"        <zone h={q(100000 // rows)} id={q(zid)} name={q(sh.name)} w={q(w)} x={q(c * w)} y={q(r * (100000 // rows))} />")
    xml = f"""    <dashboard name={q(name)}>
      <style />
      <size sizing-mode='automatic' />
      <zones>
        <zone h='100000' id='4' type-v2='layout-basic' w='100000' x='0' y='0'>
{NL.join(zones)}
        </zone>
      </zones>
    </dashboard>"""
    vps = NL.join(f"        <viewpoint name={q(s.name)} />" for s in sheets)
    window = f"""    <window class='dashboard' name={q(name)}>
      <viewpoints>
{vps}
      </viewpoints>
      <active id='-1' />
    </window>"""
    return xml, window


# ------------------------------------------------------------------ assemble
def build(data_dir: Path, extract_dir_in_workbook: str, make_extracts_in: Path | None, max_sheets: int | None = None,
          dashboards: bool = True) -> tuple[str, list[str]]:
    """Return (workbook XML, notes). Writes the .hyper files into make_extracts_in when given."""
    def load(name):
        p = data_dir / f"{name}.csv"
        return Source(name, pd.read_csv(p), f"{extract_dir_in_workbook}/{name}.hyper") if p.exists() else None

    labels_df = pd.read_csv(data_dir / "bi_dataset_labels.csv")
    L = dict(zip(labels_df["label_key"], labels_df["label_value"]))
    metric, entity = L.get("label_metric", "Volume"), L.get("label_entities", "Prescribers")
    primary = L.get("channel_calls", "Activity")
    flat, roi, dec, ic = (load(n) for n in ("bi_flat_hcp_month", "bi_channel_roi", "bi_targeting_deciles", "bi_ic_territory_quarter"))
    notes: list[str] = []
    page_a: list[Sheet] = []
    page_b: list[Sheet] = []

    if flat is not None:
        page_a.append(Sheet(f"{metric} by month", flat, "Bar", "month_start", "trx", month=True, title=f"{metric} by month"))
        page_a.append(Sheet(f"{primary} by month", flat, "Line", "month_start", "calls", month=True, title=f"{primary} by month"))
        for key, lab in (("region", L.get("label_region", "Region")), ("tier", L.get("label_tier", "Tier")), ("specialty", L.get("label_specialty", "Specialty"))):
            if flat.has(key) and flat.distinct(key) > 1:
                page_a.append(Sheet(f"{metric} by {lab}", flat, "Bar", key, "trx", title=f"{metric} by {lab.lower()}"))
            else:
                notes.append(f"'{key}' has a single value: no chart built.")
    else:
        notes.append("bi_flat_hcp_month is missing: no volume charts.")
    if roi is not None and len(roi.df):
        page_b.append(Sheet("ROI by channel", roi, "Bar", "scope_label", "roi", color="channel_label", title="ROI by channel (x per $ spent)"))
    if dec is not None and len(dec.df):
        page_b.append(Sheet("Call index by decile", dec, "Bar", "decile", "call_index", color="action", agg="Avg",
                            title=f"{primary} index by {entity.lower()} decile (1.0 = proportional to {metric})"))
    if ic is not None and len(ic.df):
        page_b.append(Sheet("Attainment by territory", ic, "Bar", "territory", "attainment_pct", agg="Avg", color="quarter", title="Quota attainment by territory (%)"))
        page_b.append(Sheet("Payout by territory", ic, "Bar", "territory", "payout", color="quarter", title="Incentive payout by territory ($)"))
    else:
        notes.append("No incentive table (needs a territory column and 15+ months): no incentive charts.")

    sheets = (page_a + page_b)[:max_sheets]
    page_a, page_b = [s for s in page_a if s in sheets], [s for s in page_b if s in sheets]
    if not sheets:
        raise SystemExit("Nothing to chart: publish the BI tables first (start the API once, or Data & reports > BI).")
    sources = list({id(s.src): s.src for s in sheets}.values())
    if make_extracts_in is not None:
        for s in sources:
            s.write_hyper(make_extracts_in / f"{s.name}.hyper")

    dash_xml, dash_windows = [], []
    if dashboards:
        for title, group in (("Performance", page_a), ("Where to focus and incentive plan", page_b)):
            if group:
                x, w = dashboard(title, group)
                dash_xml.append(x)
                dash_windows.append(w)
    windows = NL.join([sheets[i].window(maximized=(i == 0)) for i in range(len(sheets))] + dash_windows)
    dashboards_block = f"  <dashboards>{NL}{NL.join(dash_xml)}{NL}  </dashboards>{NL}" if dash_xml else ""
    xml = f"""<?xml version='1.0' encoding='utf-8' ?>

<workbook original-version={q(VERSION)} source-build={q(BUILD)} source-platform='win' version={q(VERSION)} xmlns:user='http://www.tableausoftware.com/xml/user'>
  <preferences>
    <preference name='ui.encoding.shelf.height' value='24' />
    <preference name='ui.shelf.height' value='26' />
  </preferences>
  <datasources>
{NL.join(s.xml() for s in sources)}
  </datasources>
  <worksheets>
{NL.join(s.xml() for s in sheets)}
  </worksheets>
{dashboards_block}  <windows source-height='30'>
{windows}
  </windows>
</workbook>
"""
    return xml, notes


def generate(settings: Settings, out: Path | None = None, max_sheets: int | None = None, dashboards: bool = True) -> dict:
    """Write RxLift.twb (opens in place), RxLift.twbx (self-contained) and their data into `out`."""
    out = Path(out or OUT)
    data, extracts = out / "Data", out / "Data" / "Extracts"
    if data.exists():
        shutil.rmtree(data)
    counts = bi.export_dir(settings, data)
    xml, notes = build(data, extracts.resolve().as_posix(), extracts, max_sheets, dashboards)
    (out / f"{WORKBOOK}.twb").write_text(xml, encoding="utf-8")
    xml_p, _ = build(data, "Data/Extracts", None, max_sheets, dashboards)
    pkg = out / f"{WORKBOOK}.twbx"
    with zipfile.ZipFile(pkg, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{WORKBOOK}.twb", xml_p)
        for f in sorted(extracts.glob("*.hyper")):
            z.write(f, f"Data/Extracts/{f.name}")
    return {"workbook": out / f"{WORKBOOK}.twb", "package": pkg, "tables": len(counts), "notes": notes}


def package_bytes(settings: Settings) -> bytes:
    """The self-contained .twbx as bytes (built in a throw-away folder), for download."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="pri_tableau_") as tmp:
        return generate(settings, Path(tmp))["package"].read_bytes()
