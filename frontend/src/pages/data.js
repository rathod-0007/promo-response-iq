// Data & reports: current data set, upload wizard (map your columns -> import), load history, data dictionary.
import { getJSON, postFile, postJSON } from "../api.js";
import { $, el, enhanceSelect, fmt, table } from "../ui.js";
import { state } from "../state.js";

let hooks = { onDatasetChanged: async () => {}, goto: () => {} };
export function bindData(h) { hooks = { ...hooks, ...h }; }

let spec = null;
let inspected = null;          // result of /api/upload/inspect
const dirty = new Set();       // label inputs the user edited by hand (not overwritten by auto-fill)

/* ---------- current data set ---------- */
function renderInfo(info) {
  const p = info.profile;
  const rows = [
    ["Data set", p.name], ["Source", info.source], ["Loaded", new Date(info.loaded_at).toLocaleString()],
    ["Period", `${info.first_month} to ${info.last_month}`], [p.labels.entities, fmt(info.hcps)], ["Monthly rows", fmt(info.rx_rows)],
    ["Database", `PostgreSQL, schema ${info.schema}`],
  ];
  if (p.kind === "upload") rows.push(["File", p.source_file], ["Derived by the app", p.derived.length ? p.derived.join(", ") : "nothing"]);
  const dl = $("data-info");
  dl.innerHTML = "";
  rows.forEach(([k, v]) => dl.append(el("dt", { text: k }), el("dd", { text: v })));
  $("btn-reset-sample").hidden = p.kind === "synthetic";
  const warn = $("profile-warnings");
  warn.innerHTML = "";
  (p.warnings || []).forEach((w) => warn.appendChild(el("li", { text: w })));
  $("profile-warnings-card").hidden = !(p.warnings || []).length;
}

function renderHistory(info) {
  table("t-history", [
    { key: "load_id", label: "#" }, { key: "name", label: "Data set" }, { key: "source", label: "Source" },
    { key: "loaded_at", label: "Loaded", f: (v) => new Date(v).toLocaleString() },
    { key: "summary", label: "Size", num: true, f: (v) => (v ? `${fmt(v.hcps)} x ${v.months} mo` : "") },
  ], info.history);
}

async function renderDictionary() {
  const dict = await getJSON("/api/data-dictionary");
  const root = $("dictionary");
  root.innerHTML = "";
  dict.forEach((t, i) => {
    const sum = el("summary", {}, el("strong", { text: t.name }), el("span", { class: "tag", text: t.kind }), el("span", { class: "hint", text: t.description }));
    const tb = el("table", { id: `dict-${i}` });
    root.appendChild(el("details", {}, sum, tb));
    table(tb.id, [{ key: "name", label: "Column" }, { key: "type", label: "Type" }, { key: "description", label: "Description" }], t.columns);
  });
}

/* ---------- upload wizard ---------- */
function renderRequirements() {
  const box = $("upload-reqs");
  box.innerHTML = "";
  const req = spec.roles.filter((r) => r.required), opt = spec.roles.filter((r) => !r.required);
  const line = (r) => el("li", {}, el("strong", { text: r.label }), ` — ${r.help}`);
  box.append(el("h3", { text: "Required" }), el("ul", {}, req.map(line)), el("h3", { text: "Optional" }), el("ul", {}, opt.map(line)));
  const l = spec.limits;
  box.append(el("p", { class: "sub-block", text: `One row per prescriber per month, in a CSV or Excel (.xlsx) file. Column names can be anything: you match them in the next step. Limits: ${l.max_mb} MB, ${fmt(l.max_hcps)} prescribers, ${l.max_months} months.` }));
}

function showErrors(message, issues = []) {
  const box = $("upload-errors");
  box.innerHTML = "";
  if (!message) { box.hidden = true; return; }
  box.hidden = false;
  box.append(el("strong", { text: message }));
  if (issues.length) box.append(el("ul", {}, issues.filter((i) => i !== message).map((i) => el("li", { text: i }))));
}

const roleSelects = {};          // role key -> <select>
const labelInputs = {};          // label key -> <input>

function sampleOf(col) { return (inspected.columns.find((c) => c.name === col)?.sample || []).join(", "); }

function autofillLabels() {
  const header = (role) => roleSelects[role]?.value || "";
  const defaults = {
    metric: header("trx"), "ch.calls": header("calls"), "ch.samples": header("samples"), "ch.emails": header("emails"),
    region: header("region"), specialty: header("specialty"), tier: header("tier"), territory: header("territory"), rep: header("rep"),
  };
  Object.entries(defaults).forEach(([k, v]) => {
    const input = labelInputs[k];
    if (!input || dirty.has(k)) return;
    input.value = v ? v.slice(0, 24) : "";
    input.parentElement.hidden = !v && !["metric", "ch.calls"].includes(k) ? true : false;
  });
}

function renderMapping() {
  const root = $("upload-form");
  root.innerHTML = "";
  dirty.clear();
  const cols = inspected.columns.map((c) => c.name);

  const mapRows = spec.roles.map((r) => {
    const sel = el("select", { "aria-label": r.label });
    sel.add(new Option(r.required ? "Choose a column" : "Not in my file", ""));
    cols.forEach((c) => sel.add(new Option(c, c)));
    sel.value = inspected.suggested[r.key] || "";
    roleSelects[r.key] = sel;
    const ex = el("td", { class: "ex", text: sampleOf(sel.value) });
    sel.addEventListener("change", () => { ex.textContent = sampleOf(sel.value); autofillLabels(); });
    return el("tr", {}, el("td", {}, el("strong", { text: r.label }), r.required ? el("span", { class: "tag req", text: "required" }) : null), el("td", {}, sel), ex);
  });
  const mapTable = el("table", { class: "map" }, el("thead", {}, el("tr", {}, el("th", { text: "Field" }), el("th", { text: "Column in your file" }), el("th", { text: "Example values" }))), el("tbody", {}, mapRows));

  const field = (key, label, placeholder = "") => {
    const input = el("input", { class: "control", type: "text", maxlength: "24", placeholder });
    input.addEventListener("input", () => dirty.add(key));
    labelInputs[key] = input;
    return el("div", { class: "field" }, el("span", { class: "flabel", text: label }), input);
  };
  const names = el("div", { class: "form-grid" },
    field("name", "Data set name"), field("entity", "Prescriber is called", "HCP"), field("entities", "Plural", "HCPs"),
    field("metric", "Volume is called", "Rx"), field("ch.calls", "Main channel is called", "Calls"),
    field("ch.samples", "Second channel is called"), field("ch.emails", "Third channel is called"),
    field("region", "Region is called"), field("specialty", "Specialty is called"), field("tier", "Tier is called"),
    field("territory", "Territory is called"), field("rep", "Rep is called"));

  const econ = state.meta.economics;
  const money = (key, label) => {
    const input = el("input", { class: "control", type: "number", min: "0", step: "any", placeholder: `default ${econ[key]}` });
    labelInputs[`econ.${key}`] = input;
    return el("div", { class: "field" }, el("span", { class: "flabel", text: label }), input);
  };
  const economics = el("div", { class: "form-grid" },
    money("revenue_per_trx", "Value of one volume unit ($)"), money("cost_per_call", "Cost per main-channel unit ($)"),
    money("cost_per_sample", "Cost per second-channel unit ($)"), money("cost_per_email", "Cost per third-channel unit ($)"));

  const optSelects = {};
  const optionFields = spec.options.map((o) => {
    const sel = el("select", { "aria-label": o.label });
    o.choices.forEach((c) => sel.add(new Option(c.label, c.value)));
    sel.value = o.default;
    optSelects[o.key] = sel;
    const help = el("p", { class: "hint-block", text: o.choices.find((c) => c.value === sel.value).help });
    sel.addEventListener("change", () => { help.textContent = o.choices.find((c) => c.value === sel.value).help; });
    return el("div", { class: "field wide" }, el("span", { class: "flabel", text: o.label }), sel, help);
  });

  const btn = el("button", { class: "btn", type: "button", id: "btn-import", text: "Import and switch data set" });
  btn.addEventListener("click", () => doImport(optSelects, btn));
  root.append(
    el("div", { class: "step" }, el("h3", { text: `1 · Match your columns (${inspected.filename}, ${fmt(inspected.rows)} rows)` }), mapTable),
    el("div", { class: "step" }, el("h3", { text: "2 · Name things the way your team does" }), names),
    el("div", { class: "step" }, el("h3", { text: "3 · Economics (optional)" }), economics),
    el("div", { class: "step" }, el("h3", { text: "4 · Data handling" }), el("div", { class: "form-grid" }, optionFields)),
    el("div", { class: "actions-row" }, btn));
  Object.values(roleSelects).forEach((s) => enhanceSelect(s));
  Object.values(optSelects).forEach((s) => enhanceSelect(s));
  labelInputs.name.value = inspected.filename.replace(/\.[^.]+$/, "");
  autofillLabels();
  root.hidden = false;
}

function collect(optSelects) {
  const mapping = {};
  Object.entries(roleSelects).forEach(([k, s]) => { if (s.value) mapping[k] = s.value; });
  const v = (k) => labelInputs[k]?.value.trim();
  const labels = { channels: {} };
  ["entity", "entities", "metric", "region", "specialty", "tier", "territory", "rep"].forEach((k) => { if (v(k)) labels[k] = v(k); });
  ["calls", "samples", "emails"].forEach((k) => { if (v(`ch.${k}`)) labels.channels[k] = v(`ch.${k}`); });
  const economics = {};
  ["revenue_per_trx", "cost_per_call", "cost_per_sample", "cost_per_email"].forEach((k) => { if (v(`econ.${k}`)) economics[k] = Number(v(`econ.${k}`)); });
  const options = { name: v("name"), labels, economics };
  Object.entries(optSelects).forEach(([k, s]) => { options[k] = s.value; });
  return { upload_id: inspected.upload_id, mapping, options };
}

async function doImport(optSelects, btn) {
  showErrors("");
  btn.disabled = true;
  btn.textContent = "Importing...";
  try {
    const res = await postJSON("/api/upload/import", collect(optSelects));
    await hooks.onDatasetChanged();
    renderResult(res);
    $("upload-form").hidden = true;
    inspected = null;
    await load();
  } catch (e) {
    showErrors(e.message, e.issues);
  } finally {
    btn.disabled = false;
    btn.textContent = "Import and switch data set";
  }
}

function renderResult(res) {
  const box = $("upload-result");
  box.hidden = false;
  box.innerHTML = "";
  const s = res.summary;
  box.append(
    el("strong", { text: `Loaded "${res.name}"` }),
    el("p", { text: `${fmt(s.hcps)} prescribers over ${s.months} months (${s.first_month} to ${s.last_month}); ${fmt(s.rows_loaded)} rows${s.territories ? `, ${s.territories} territories` : ""}. All pages now use this data and its wording.` }),
    res.warnings.length ? el("ul", {}, res.warnings.map((w) => el("li", { text: w }))) : null,
    el("button", { class: "btn", type: "button", text: "Open overview", onclick: () => hooks.goto("overview") }));
}

async function onFile(file) {
  if (!file) return;
  showErrors("");
  $("upload-result").hidden = true;
  $("drop-name").textContent = `Reading ${file.name}...`;
  try {
    inspected = await postFile("/api/upload/inspect", file);
    $("drop-name").textContent = file.name;
    renderMapping();
  } catch (e) {
    inspected = null;
    $("upload-form").hidden = true;
    $("drop-name").textContent = "Choose a CSV or Excel file";
    showErrors(e.message, e.issues);
  }
}

export function bindUpload() {
  const input = $("file-input"), drop = $("dropzone");
  input.addEventListener("change", () => { onFile(input.files[0]); input.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => onFile(e.dataTransfer.files[0]));
  $("btn-reset-sample").addEventListener("click", async () => {
    if (!window.confirm("Replace the current data with the built-in synthetic sample data?")) return;
    await postJSON("/api/data/reset-sample");
    await hooks.onDatasetChanged();
    $("upload-result").hidden = true;
    await load();
  });
}

export async function load() {
  const [info] = await Promise.all([getJSON("/api/data-info"), spec ? null : getJSON("/api/upload/spec").then((s) => { spec = s; })]);
  renderInfo(info);
  renderHistory(info);
  if (!$("upload-reqs").childElementCount) renderRequirements();
  await renderDictionary();
}
