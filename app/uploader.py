"""User data upload: read a CSV / Excel extract, map its columns to analysis roles, validate, and load it.

One flat table is expected: one row per prescriber per month. Column NAMES are free (they are mapped to roles);
only the roles below matter. Anything optional that is missing is handled (derived or hidden), never invented silently:
every derivation and clean-up is reported back as a warning.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

from .config import ROOT, Settings
from .db import load_frames


class UploadError(ValueError):
    def __init__(self, message: str, issues: list[str] | None = None):
        super().__init__(message)
        self.issues = issues or [message]


# ---- roles (served to the UI, so the mapping form is generated from this, not hard-coded there) ----
ROLES = [
    {"key": "hcp_id", "label": "Prescriber ID", "required": True, "kind": "id", "example": "1043921",
     "help": "Unique ID of each prescriber or account (NPI, customer ID...). Text or number.",
     "synonyms": ["hcpid", "npi", "prescriberid", "providerid", "physicianid", "accountid", "customerid", "doctorid", "id"]},
    {"key": "month", "label": "Month", "required": True, "kind": "date", "example": "2025-01",
     "help": "Reporting month. YYYY-MM, YYYY-MM-DD, 01/2025, Jan-2025, 202501 or an Excel date.",
     "synonyms": ["month", "period", "reportingmonth", "yearmonth", "monthyear", "date", "ym"]},
    {"key": "trx", "label": "Prescriptions (volume)", "required": True, "kind": "number", "example": "14",
     "help": "Outcome to explain: TRx, NBRx, units or sales for that prescriber and month. Not negative.",
     "synonyms": ["trx", "nbrx", "rx", "totalrx", "prescriptions", "scripts", "units", "volume", "sales", "quantity", "qty"]},
    {"key": "calls", "label": "Main promotion channel", "required": True, "kind": "number", "example": "3",
     "help": "Your main field activity, e.g. calls or detail visits per prescriber and month. Drives the optimizer.",
     "synonyms": ["calls", "details", "detailvisits", "detailing", "visits", "f2f", "repcalls", "callactivity"]},
    {"key": "samples", "label": "Second channel (optional)", "required": False, "kind": "number", "example": "4",
     "help": "e.g. samples dropped. Leave unmapped if you do not have it.",
     "synonyms": ["samples", "sampledrops", "sampling", "sampledrop"]},
    {"key": "emails", "label": "Third channel (optional)", "required": False, "kind": "number", "example": "6",
     "help": "e.g. approved e-mails or other digital touches. Leave unmapped if you do not have it.",
     "synonyms": ["emails", "email", "emailsends", "emailsent", "digital", "approvedemails"]},
    {"key": "hcp_name", "label": "Prescriber name", "required": False, "kind": "text", "example": "Dr. A. Rao",
     "help": "Shown in tables. The ID is used when missing.",
     "synonyms": ["hcpname", "prescribername", "providername", "physician", "doctor", "name", "prescriber"]},
    {"key": "region", "label": "Region / state", "required": False, "kind": "text", "example": "West",
     "help": "Becomes a filter and a breakdown when it has more than one value.",
     "synonyms": ["region", "state", "area", "zone", "geography", "geo", "district"]},
    {"key": "specialty", "label": "Specialty", "required": False, "kind": "text", "example": "Cardiology",
     "help": "Becomes a filter and a breakdown when it has more than one value.",
     "synonyms": ["specialty", "speciality", "specialtygroup", "spec"]},
    {"key": "tier", "label": "Value tier / segment", "required": False, "kind": "text", "example": "A",
     "help": "Any labels (A/B/C, Gold/Silver...). Derived from prescription volume when not supplied.",
     "synonyms": ["tier", "segment", "decile", "class", "potential", "targetclass"]},
    {"key": "territory", "label": "Territory", "required": False, "kind": "text", "example": "West 01",
     "help": "Enables incentive compensation (needs at least 15 months of data).",
     "synonyms": ["territory", "territoryid", "territoryname", "terr", "salesterritory"]},
    {"key": "rep", "label": "Rep name", "required": False, "kind": "text", "example": "Rep West 01",
     "help": "Field rep who owns the territory.",
     "synonyms": ["rep", "repname", "salesrep", "representative"]},
]
OPTIONS = [
    {"key": "duplicates", "label": "Duplicate prescriber-months", "default": "sum", "choices": [
        {"value": "sum", "label": "Sum them", "help": "Several rows for the same prescriber and month (e.g. one per product) are added together."},
        {"value": "error", "label": "Reject the file", "help": "Stop and report the first duplicate."}]},
    {"key": "missing", "label": "Prescriber-months with no row", "default": "zero", "choices": [
        {"value": "zero", "label": "Treat as 0", "help": "Right when a missing row really means no activity and no prescriptions."},
        {"value": "exclude", "label": "Exclude those prescribers", "help": "Safer when gaps are data errors: zero-filling genuine gaps overstates how much activity drives prescribing."},
        {"value": "error", "label": "Reject the file", "help": "Stop and report how many are missing."}]},
]
ROLE_KEYS = [r["key"] for r in ROLES]
REQUIRED_ROLES = [r["key"] for r in ROLES if r["required"]]
ALLOWED_EXT = (".csv", ".tsv", ".txt", ".xlsx")
SAFE_ID = re.compile(r"^[0-9a-f]{32}$")


def spec(settings: Settings) -> dict:
    u = settings.upload
    public = [{k: v for k, v in r.items() if k != "synonyms"} for r in ROLES]
    return {"roles": public, "options": OPTIONS, "extensions": list(ALLOWED_EXT),
            "limits": {"max_mb": u["max_mb"], "max_rows": u["max_rows"], "max_hcps": u["max_hcps"],
                       "max_months": u["max_months"], "max_tiers": u["max_tiers"]},
            "derived_tier_shares": u["derived_tier_shares"]}


def template_csv() -> str:
    header = [r["key"] for r in ROLES]
    rows = [[r["example"] for r in ROLES]]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


# ---- storage ----
def _upload_dir(settings: Settings) -> Path:
    d = Path(settings.upload["dir"])
    d = d if d.is_absolute() else ROOT / d
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_upload(settings: Settings, filename: str, data: bytes) -> str:
    name = Path(filename or "upload").name
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise UploadError(f"Unsupported file type '{ext or name}'. Use one of: {', '.join(ALLOWED_EXT)}.")
    if not data:
        raise UploadError("The file is empty.")
    if len(data) > settings.upload["max_mb"] * 1024 * 1024:
        raise UploadError(f"File is larger than the {settings.upload['max_mb']} MB limit.")
    upload_id = uuid.uuid4().hex
    folder = _upload_dir(settings) / upload_id
    folder.mkdir()
    (folder / re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]).write_bytes(data)
    return upload_id


def _find_file(settings: Settings, upload_id: str) -> Path:
    if not SAFE_ID.match(upload_id or ""):
        raise UploadError("Unknown upload. Choose the file again.")
    folder = _upload_dir(settings) / upload_id
    files = [f for f in folder.glob("*") if f.is_file()] if folder.is_dir() else []
    if not files:
        raise UploadError("Unknown upload. Choose the file again.")
    return files[0]


def read_table(settings: Settings, path: Path) -> pd.DataFrame:
    ext = path.suffix.lower()
    try:
        if ext == ".xlsx":
            raw = pd.read_excel(path, dtype=str, engine="openpyxl", keep_default_na=False, header=None)
        else:
            raw = path.read_bytes()
            try:
                text_ = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text_ = raw.decode("latin-1")
            try:
                delim = csv.Sniffer().sniff(text_[:8192], delimiters=",;\t|").delimiter
            except csv.Error:
                delim = ","
            raw = pd.read_csv(io.StringIO(text_), sep=delim, dtype=str, keep_default_na=False, skipinitialspace=True, header=None)
    except Exception as e:  # unreadable / corrupt file
        raise UploadError(f"Could not read the file: {e}") from e
    if raw.empty:
        raise UploadError("The file is empty.")
    df = raw.iloc[1:].reset_index(drop=True)           # header read raw so duplicate names are not silently renamed
    df.columns = [str(c).strip() for c in raw.iloc[0]]
    if any(c == "" for c in df.columns):
        raise UploadError("Every column needs a header name in the first row.")
    dup = sorted({c for c in df.columns if list(df.columns).count(c) > 1})
    if dup:
        raise UploadError(f"Duplicate column names: {', '.join(dup)}. Rename them so each is unique.")
    df = df.apply(lambda s: s.str.strip())
    df = df[~(df == "").all(axis=1)].reset_index(drop=True)
    if df.empty:
        raise UploadError("The file has headers but no data rows.")
    if len(df) > settings.upload["max_rows"]:
        raise UploadError(f"The file has {len(df):,} rows; the limit is {settings.upload['max_rows']:,}.")
    return df


# ---- parsing helpers ----
def _month_of(value: str):
    v = value.strip()
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})(?:[-/.]\d{1,2})?(?:[ T].*)?", v)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
    elif (m := re.fullmatch(r"(\d{1,2})[-/.](\d{4})", v)):
        mo, y = int(m.group(1)), int(m.group(2))
    elif re.fullmatch(r"\d{6}", v):
        y, mo = int(v[:4]), int(v[4:])
    elif re.fullmatch(r"\d{5}(\.\d+)?", v):  # Excel serial date
        ts = pd.Timestamp("1899-12-30") + pd.to_timedelta(float(v), unit="D")
        y, mo = ts.year, ts.month
    else:
        ts = pd.to_datetime(v, errors="coerce", format="mixed")
        if pd.isna(ts):
            return None
        y, mo = ts.year, ts.month
    return f"{y:04d}-{mo:02d}" if 1990 <= y <= 2100 and 1 <= mo <= 12 else None


def _parse_months(series: pd.Series, col: str, issues: list[str]) -> pd.Series:
    lookup = {v: _month_of(v) if v else None for v in series.unique()}
    out = series.map(lookup)
    bad = out.isna()
    if bad.any():
        rows = ", ".join(str(i + 2) for i in series.index[bad][:5])
        examples = ", ".join(repr(v) for v in series[bad].unique()[:3])
        issues.append(f"Column '{col}': {int(bad.sum())} value(s) are not valid months (e.g. {examples}; file rows {rows}).")
    return out


def _to_number(series: pd.Series, col: str, issues: list[str], warnings: list[str], what: str) -> pd.Series:
    s = series.str.replace(r"[\s$€£]", "", regex=True).str.replace(",", "", regex=False).str.replace("%", "", regex=False)
    s = s.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    num = pd.to_numeric(s.replace("", np.nan), errors="coerce")
    bad = num.isna() & (series != "")
    if bad.any():
        rows = ", ".join(str(i + 2) for i in series.index[bad][:5])
        examples = ", ".join(repr(v) for v in series[bad].unique()[:3])
        issues.append(f"Column '{col}' ({what}): {int(bad.sum())} value(s) are not numbers (e.g. {examples}; file rows {rows}).")
    neg = num < 0
    if neg.any():
        rows = ", ".join(str(i + 2) for i in series.index[neg][:5])
        issues.append(f"Column '{col}' ({what}): {int(neg.sum())} negative value(s) (file rows {rows}). Counts cannot be negative.")
    blank = int((series == "").sum())
    if blank:
        warnings.append(f"Column '{col}' ({what}): {blank:,} blank value(s) were treated as 0.")
    frac = num.notna() & (np.abs(num - np.rint(num)) > 1e-9)
    if frac.any():
        warnings.append(f"Column '{col}' ({what}): {int(frac.sum()):,} fractional value(s) were rounded to whole numbers.")
    return num.fillna(0.0).round().astype(float)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def suggest_mapping(columns: list[str]) -> dict:
    """Best-guess role -> column, by exact then partial match of normalised header names."""
    norm = {c: _norm(c) for c in columns}
    taken: set[str] = set()
    out: dict[str, str] = {}
    for exact in (True, False):
        for role in ROLES:
            if role["key"] in out:
                continue
            for col, n in norm.items():
                if col in taken:
                    continue
                hit = n in role["synonyms"] if exact else any(len(s) >= 4 and s in n for s in role["synonyms"])
                if hit:
                    out[role["key"]] = col
                    taken.add(col)
                    break
    return out


def _guess_kind(values: pd.Series) -> str:
    sample = values[values != ""].head(200)
    if sample.empty:
        return "empty"
    num = pd.to_numeric(sample.str.replace(r"[\s$€£,%]", "", regex=True), errors="coerce").notna().mean()
    dates = np.mean([_month_of(v) is not None for v in sample.head(50)])
    if dates >= 0.9 and not (num >= 0.9 and sample.str.fullmatch(r"\d{1,4}").mean() > 0.9):
        return "date"
    return "number" if num >= 0.9 else "text"


def inspect(settings: Settings, upload_id: str) -> dict:
    path = _find_file(settings, upload_id)
    df = read_table(settings, path)
    cols = []
    for c in df.columns:
        non_empty = df[c][df[c] != ""]
        cols.append({"name": c, "kind": _guess_kind(df[c]), "filled_pct": round(len(non_empty) / len(df) * 100, 1),
                     "distinct": int(non_empty.nunique()), "sample": [str(v) for v in non_empty.unique()[:3]]})
    return {"upload_id": upload_id, "filename": path.name, "rows": int(len(df)), "columns": cols,
            "suggested": suggest_mapping(list(df.columns)),
            "preview": df.head(5).to_dict("records")}


# ---- transform ----
def _singular(label: str) -> str:
    low = label.strip().lower()
    return low[:-1] if low.endswith("s") and len(low) > 3 else low


def _mode(s: pd.Series):
    s = s.dropna()
    return s.mode().iloc[0] if len(s) else np.nan


def _label(opts: dict, key: str, default: str, maxlen: int = 24) -> str:
    v = str(opts.get(key) or "").strip()[:maxlen]
    return v or default


def build_dataset(settings: Settings, df: pd.DataFrame, mapping: dict, options: dict | None = None,
                  filename: str = "upload") -> dict:
    options = options or {}
    up = settings.upload
    issues: list[str] = []
    warnings: list[str] = []
    derived: list[str] = []

    mapping = {k: v for k, v in (mapping or {}).items() if v}
    for k in mapping:
        if k not in ROLE_KEYS:
            issues.append(f"Unknown field '{k}' in the mapping.")
    for k in REQUIRED_ROLES:
        if k not in mapping:
            issues.append(f"Choose a column for '{next(r['label'] for r in ROLES if r['key'] == k)}'.")
    for k, col in mapping.items():
        if col not in df.columns:
            issues.append(f"Column '{col}' (for {k}) is not in the file.")
    used = [c for c in mapping.values()]
    for c in {c for c in used if used.count(c) > 1}:
        issues.append(f"Column '{c}' is mapped to more than one field.")
    if issues:
        raise UploadError("The column mapping needs attention.", issues)

    w = pd.DataFrame(index=df.index)
    w["ext"] = df[mapping["hcp_id"]]
    blank_id = w["ext"] == ""
    if blank_id.any():
        rows = ", ".join(str(i + 2) for i in w.index[blank_id][:5])
        issues.append(f"Column '{mapping['hcp_id']}': {int(blank_id.sum())} row(s) have no prescriber ID (file rows {rows}).")
    w["month"] = _parse_months(df[mapping["month"]], mapping["month"], issues)
    w["trx"] = _to_number(df[mapping["trx"]], mapping["trx"], issues, warnings, "prescriptions")
    w["calls"] = _to_number(df[mapping["calls"]], mapping["calls"], issues, warnings, "main channel")
    for key, what in (("samples", "second channel"), ("emails", "third channel")):
        w[key] = _to_number(df[mapping[key]], mapping[key], issues, warnings, what) if key in mapping else 0.0
    for key in ("hcp_name", "region", "specialty", "tier", "territory", "rep"):
        w[key] = df[mapping[key]].replace("", np.nan) if key in mapping else np.nan
    if issues:
        raise UploadError("The file has data problems to fix.", issues)

    # duplicates (same prescriber + month)
    dup = w.duplicated(["ext", "month"], keep=False)
    if dup.any():
        n = int(w.duplicated(["ext", "month"]).sum())
        if options.get("duplicates") == "error":
            first = w[dup].iloc[0]
            raise UploadError("Duplicate prescriber-months found.", [
                f"{n:,} duplicate prescriber-month row(s), e.g. prescriber {first['ext']!r} in {first['month']}. "
                "Fix the file or choose 'sum duplicates'."])
        warnings.append(f"{n:,} duplicate prescriber-month row(s) were summed.")
    agg = {c: "sum" for c in ("trx", "calls", "samples", "emails")}
    agg.update({c: "first" for c in ("hcp_name", "region", "specialty", "tier", "territory", "rep")})
    g = w.groupby(["ext", "month"], as_index=False, sort=True).agg(agg)

    # coverage
    months = sorted(g["month"].unique())
    full = [str(p) for p in pd.period_range(months[0], months[-1], freq="M")]
    if len(full) > up["max_months"]:
        raise UploadError(f"The file spans {len(full)} months; the limit is {up['max_months']}.")
    missing_months = [m for m in full if m not in set(months)]
    if missing_months:
        raise UploadError("There are gaps in the calendar.", [
            f"No rows at all for month(s): {', '.join(missing_months[:6])}. Months must be continuous; add them or trim the range."])
    hcps = sorted(g["ext"].unique())
    if len(hcps) > up["max_hcps"]:
        raise UploadError(f"The file has {len(hcps):,} prescribers; the limit is {up['max_hcps']:,}.")
    if len(hcps) * len(full) > up["max_rows"]:
        raise UploadError(f"{len(hcps):,} prescribers x {len(full)} months is more than {up['max_rows']:,} rows.")
    if len(full) < 4:
        raise UploadError("At least 4 months of data are needed for the response model.")

    grid = pd.MultiIndex.from_product([hcps, full], names=["ext", "month"])
    g = g.set_index(["ext", "month"]).reindex(grid)
    policy = options.get("missing") or ("zero" if options.get("fill_missing", True) else "error")
    if policy not in ("zero", "exclude", "error"):
        raise UploadError("Invalid option.", [f"'missing' must be zero, exclude or error (got {policy!r})."])
    gap = g["trx"].isna()
    absent = int(gap.sum())
    if absent:
        share = absent / len(g) * 100
        if policy == "error":
            raise UploadError("The data is not a complete prescriber x month grid.", [
                f"{absent:,} prescriber-month(s) have no row. Add them, or choose to treat them as 0 or exclude those prescribers."])
        if policy == "exclude":
            bad = set(g.index[gap].get_level_values("ext"))
            g = g[~g.index.get_level_values("ext").isin(bad)]
            hcps = [h for h in hcps if h not in bad]
            if not hcps:
                raise UploadError("Every prescriber has a missing month.", ["Nothing is left after excluding incomplete prescribers."])
            warnings.append(f"{len(bad):,} prescriber(s) with missing months ({absent:,} gaps) were excluded; {len(hcps):,} complete prescribers remain.")
        else:
            warnings.append(f"{absent:,} prescriber-month(s) ({share:.1f}%) had no row and were set to 0 activity and 0 prescriptions."
                            + (" If these are data gaps rather than true zeros, re-import and choose 'Exclude those prescribers': "
                               "zero-filling gaps can overstate the response to promotion." if share >= 0.5 else ""))
    for c in ("trx", "calls", "samples", "emails"):
        g[c] = g[c].fillna(0).astype(int)
    g = g.reset_index()
    if g["trx"].sum() == 0:
        raise UploadError("All prescription values are 0.", ["The prescription column has no volume to analyse."])
    if g["calls"].sum() == 0:
        raise UploadError("The main promotion channel is all 0.", ["Map a channel that has activity (e.g. calls)."])

    # one row per prescriber
    ids = {ext: i + 1 for i, ext in enumerate(hcps)}
    attr = g.groupby("ext")[["hcp_name", "region", "specialty", "tier", "territory", "rep"]].agg(_mode).reindex(hcps).astype(object)
    for col in ("region", "specialty", "tier", "territory"):
        if col in mapping:
            changing = int((w.groupby("ext")[col].nunique(dropna=True) > 1).sum())
            if changing:
                warnings.append(f"{changing:,} prescriber(s) have more than one '{mapping[col]}' value; the most common one was used.")
    hcp = pd.DataFrame({"hcp_id": [ids[e] for e in hcps], "external_id": hcps})
    hcp["name"] = attr["hcp_name"].fillna(pd.Series(hcps, index=attr.index)).to_numpy()
    hcp["region"] = attr["region"].fillna("Unspecified" if "region" in mapping else "All").to_numpy()
    hcp["specialty"] = attr["specialty"].fillna("Unspecified" if "specialty" in mapping else "All").to_numpy()
    totals = g.groupby("ext")["trx"].sum().reindex(hcps)
    if "tier" in mapping:
        hcp["tier"] = attr["tier"].fillna("Unassigned").astype(str).to_numpy()
        if hcp["tier"].nunique() > up["max_tiers"]:
            raise UploadError("Too many tier values.", [f"'{mapping['tier']}' has {hcp['tier'].nunique()} distinct values; "
                                                        f"at most {up['max_tiers']} are supported. Map a coarser segment column."])
    else:
        shares = list(up["derived_tier_shares"].items())
        order = totals.rank(method="first", ascending=False).to_numpy() / len(hcps)
        edges = np.cumsum([s for _, s in shares]) / sum(s for _, s in shares)
        tier_names = [n for n, _ in shares]
        hcp["tier"] = [tier_names[min(int(np.searchsorted(edges, o - 1e-12)), len(tier_names) - 1)] for o in order]
        derived.append("tier")
        total_share = sum(sh for _, sh in shares)
        parts = ", ".join(f"{n} = {'top' if i == 0 else 'next'} {int(round(sh / total_share * 100))}%" for i, (n, sh) in enumerate(shares))
        warnings.append(f"No tier column was mapped, so tiers were derived from total prescription volume ({parts}).")

    territory = None
    if "territory" in mapping:
        tnames = sorted(attr["territory"].dropna().unique())
        if tnames:
            tid = {t: i + 1 for i, t in enumerate(tnames)}
            hcp["territory_id"] = pd.array([tid.get(t) if isinstance(t, str) else None for t in attr["territory"]], dtype="Int64")
            tdf = pd.DataFrame({"name": tnames})
            tdf["territory_id"] = [tid[t] for t in tnames]
            by_t = pd.DataFrame({"t": attr["territory"].to_numpy(), "region": hcp["region"].to_numpy(),
                                 "rep": attr["rep"].to_numpy()}).dropna(subset=["t"]).groupby("t").agg(region=("region", _mode), rep=("rep", _mode))
            tdf["region"] = [by_t.loc[t, "region"] for t in tnames]
            tdf["rep_name"] = [by_t.loc[t, "rep"] if isinstance(by_t.loc[t, "rep"], str) else f"Rep {t}" for t in tnames]
            territory = tdf[["territory_id", "name", "region", "rep_name"]]
            unassigned = int(hcp["territory_id"].isna().sum())
            if unassigned:
                warnings.append(f"{unassigned:,} prescriber(s) have no territory and are left out of incentive compensation.")
            if len(full) < 15:
                warnings.append("Incentive compensation needs same-quarter data from the previous year (at least 15 months); "
                                "that page will explain this until more history is loaded.")
    else:
        warnings.append("No territory column was mapped: the incentive compensation page stays unavailable.")

    activity = g[["ext", "month", "calls", "samples", "emails"]].assign(hcp_id=lambda d: d["ext"].map(ids))[["hcp_id", "month", "calls", "samples", "emails"]]
    rx = g[["ext", "month", "trx"]].assign(hcp_id=lambda d: d["ext"].map(ids))[["hcp_id", "month", "trx"]]
    if len(activity) < settings.model["min_observations"]:
        warnings.append(f"Only {len(activity):,} prescriber-months: the response model needs at least {settings.model['min_observations']}.")

    # profile: names shown everywhere, and per-data-set economics
    lb = options.get("labels") or {}
    ch_labels = lb.get("channels") if isinstance(lb.get("channels"), dict) else {}
    channels = []
    for key, default_label in (("calls", "Calls"), ("samples", "Samples"), ("emails", "E-mails")):
        label = _label(ch_labels, key, mapping[key][:24] if key in mapping else default_label)
        active = key in mapping and bool(g[key].sum() > 0)
        if key in mapping and not active:
            warnings.append(f"Channel '{mapping[key]}' is all 0 and was left out of the analysis.")
        channels.append({"key": key, "label": label, "unit": _singular(label), "active": True if key == "calls" else active})
    entity = _label(lb, "entity", "HCP")
    labels = {"entity": entity, "entities": _label(lb, "entities", entity + "s"),
              "metric": _label(lb, "metric", mapping["trx"][:24]), "metric_long": "prescriptions",
              "region": _label(lb, "region", mapping.get("region", "Region")[:24]),
              "specialty": _label(lb, "specialty", mapping.get("specialty", "Specialty")[:24]),
              "tier": _label(lb, "tier", mapping.get("tier", "Tier")[:24]),
              "territory": _label(lb, "territory", mapping.get("territory", "Territory")[:24]),
              "rep": _label(lb, "rep", mapping.get("rep", "Rep")[:24])}
    econ_in = options.get("economics") or {}
    econ: dict = {}
    for key in ("revenue_per_trx", "cost_per_call", "cost_per_sample", "cost_per_email"):
        if econ_in.get(key) in (None, ""):
            continue
        try:
            val = float(econ_in[key])
        except (TypeError, ValueError):
            raise UploadError("Invalid economics.", [f"'{key}' must be a number."])
        if (key in ("revenue_per_trx", "cost_per_call") and val <= 0) or val < 0:
            raise UploadError("Invalid economics.", [f"'{key}' must be {'greater than' if key in ('revenue_per_trx', 'cost_per_call') else 'at least'} 0."])
        econ[key] = val
    if not econ.get("revenue_per_trx"):
        warnings.append(f"No value per {labels['metric']} was given, so the default from config.json is used for revenue and ROI.")

    profile = {"name": str(options.get("name") or filename)[:80], "kind": "upload", "source_file": filename,
               "labels": labels, "channels": channels, "economics": econ, "mapping": mapping,
               "derived": derived, "warnings": warnings}
    summary = {"hcps": len(hcps), "months": len(full), "first_month": full[0], "last_month": full[-1],
               "rows_in_file": int(len(df)), "rows_loaded": int(len(activity)), "territories": 0 if territory is None else len(territory)}
    return {"hcp": hcp[["hcp_id", "external_id", "name", "specialty", "region", "tier"] + (["territory_id"] if "territory_id" in hcp else [])],
            "activity": activity, "rx": rx, "territory": territory, "profile": profile, "summary": summary}


def import_upload(settings: Settings, upload_id: str, mapping: dict, options: dict | None = None) -> dict:
    path = _find_file(settings, upload_id)
    df = read_table(settings, path)
    built = build_dataset(settings, df, mapping, options, filename=path.name)
    profile = built["profile"]
    profile["summary"] = built["summary"]
    load_frames(settings, built["hcp"], built["activity"], built["rx"], f"upload:{path.name}", built["territory"], profile)
    return {"summary": built["summary"], "warnings": profile["warnings"], "derived": profile["derived"], "name": profile["name"]}
