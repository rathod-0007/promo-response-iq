"use strict";

const $ = (id) => document.getElementById(id);
const FILTER_IDS = { region: "f-region", specialty: "f-specialty", tier: "f-tier", start: "f-start", end: "f-end" };
const charts = {};
let meta = null;

const fmt = (n, d = 0) => (n === null || n === undefined ? "n/a" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));
const money = (n) => (n === null || n === undefined ? "n/a" : (n < 0 ? "-$" : "$") + fmt(Math.abs(n)));

function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

function filterParams() {
  const p = new URLSearchParams();
  for (const [k, id] of Object.entries(FILTER_IDS)) { const v = $(id).value; if (v) p.set(k, v); }
  return p;
}

async function api(path, extra = {}) {
  const p = filterParams();
  for (const [k, v] of Object.entries(extra)) p.set(k, v);
  const res = await fetch(`${path}?${p}`);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) { /* ignore */ }
    const err = new Error(detail); err.status = res.status; throw err;
  }
  return res.json();
}

function monthLabels(lo, hi) {
  const out = []; let [y, m] = lo.split("-").map(Number); const [hy, hm] = hi.split("-").map(Number);
  while (y < hy || (y === hy && m <= hm)) { out.push(`${y}-${String(m).padStart(2, "0")}`); m++; if (m > 12) { m = 1; y++; } }
  return out;
}

function fillSelect(id, options, allLabel, selected = "") {
  const el = $(id); el.innerHTML = "";
  if (allLabel) el.add(new Option(allLabel, ""));
  options.forEach((o) => el.add(new Option(o, o)));
  el.value = selected;
}

/* Searchable dropdown layered over a native <select> (which stays the source of truth). */
const combos = [];
function enhanceSelect(sel) {
  if (sel._combo) { sel._combo.rebuild(); return; }
  const wrap = document.createElement("div"); wrap.className = "combo";
  sel.parentNode.insertBefore(wrap, sel); wrap.appendChild(sel); sel.classList.add("native");
  const btn = document.createElement("button"); btn.type = "button"; btn.className = "combo-btn";
  btn.setAttribute("aria-haspopup", "listbox"); btn.setAttribute("aria-expanded", "false");
  const label = document.createElement("span"); const caret = document.createElement("i"); caret.className = "caret";
  btn.append(label, caret);
  const pop = document.createElement("div"); pop.className = "combo-pop"; pop.hidden = true;
  const search = document.createElement("input"); search.type = "search"; search.placeholder = "Search..."; search.setAttribute("aria-label", "Search options");
  const list = document.createElement("ul"); list.setAttribute("role", "listbox");
  const empty = document.createElement("div"); empty.className = "combo-empty"; empty.textContent = "No matches"; empty.hidden = true;
  pop.append(search, list, empty); wrap.append(btn, pop);
  let active = -1;

  const items = () => [...list.children];
  const sync = () => { label.textContent = sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].text : ""; items().forEach((li) => li.classList.toggle("sel", li.dataset.value === sel.value)); };
  const setActive = (i) => { const it = items().filter((li) => !li.hidden); active = Math.max(0, Math.min(i, it.length - 1)); items().forEach((li) => li.classList.remove("act")); if (it[active]) { it[active].classList.add("act"); it[active].scrollIntoView({ block: "nearest" }); } };
  const filter = () => { const q = search.value.trim().toLowerCase(); let n = 0; items().forEach((li) => { const show = li.textContent.toLowerCase().includes(q); li.hidden = !show; if (show) n++; }); empty.hidden = n > 0; setActive(0); };
  const close = () => { pop.hidden = true; btn.setAttribute("aria-expanded", "false"); };
  const open = () => { combos.forEach((c) => c.close()); pop.hidden = false; btn.setAttribute("aria-expanded", "true"); search.value = ""; filter(); search.focus(); };
  const choose = (v) => { sel.value = v; sync(); close(); sel.dispatchEvent(new Event("change")); btn.focus(); };
  const rebuild = () => {
    list.innerHTML = "";
    [...sel.options].forEach((o) => { const li = document.createElement("li"); li.setAttribute("role", "option"); li.dataset.value = o.value; li.textContent = o.text; li.addEventListener("click", () => choose(o.value)); list.appendChild(li); });
    sync();
  };
  btn.addEventListener("click", () => (pop.hidden ? open() : close()));
  search.addEventListener("input", filter);
  search.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
    else if (e.key === "Enter") { e.preventDefault(); const a = items().filter((li) => !li.hidden)[active]; if (a) choose(a.dataset.value); }
    else if (e.key === "Escape") { close(); btn.focus(); }
  });
  document.addEventListener("click", (e) => { if (!wrap.contains(e.target)) close(); });
  sel._combo = { rebuild, sync, close }; combos.push(sel._combo); rebuild();
}
const syncSelects = () => combos.forEach((c) => c.sync());

function table(id, cols, rows) {
  const t = $(id); t.innerHTML = "";
  const head = t.createTHead().insertRow();
  cols.forEach((c) => { const th = document.createElement("th"); th.textContent = c.label; if (c.num) th.className = "num"; head.appendChild(th); });
  const body = t.createTBody();
  rows.forEach((r) => {
    const tr = body.insertRow();
    cols.forEach((c) => { const td = tr.insertCell(); td.textContent = c.f ? c.f(r[c.key], r) : r[c.key]; if (c.num) td.className = "num"; });
  });
}

function kpiCards(id, items) {
  const el = $(id); el.innerHTML = "";
  items.forEach((k) => {
    const d = document.createElement("div"); d.className = "kpi";
    const s = document.createElement("span"); s.textContent = k.label;
    const b = document.createElement("strong"); b.textContent = k.value;
    d.append(s, b);
    if (k.sub) { const e = document.createElement("em"); e.textContent = k.sub; if (k.tone) e.className = k.tone; d.appendChild(e); }
    el.appendChild(d);
  });
}

function draw(id, config) {
  if (charts[id]) charts[id].destroy();
  Chart.defaults.color = cssVar("--muted");
  Chart.defaults.borderColor = cssVar("--border");
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 11;
  Chart.defaults.borderColor = cssVar("--rule");
  charts[id] = new Chart($(id), { ...config, options: { responsive: true, maintainAspectRatio: false, ...config.options } });
}

function clearModelPanels() {
  ["c-elast", "c-roi"].forEach((id) => { if (charts[id]) { charts[id].destroy(); delete charts[id]; } });
  ["t-model", "t-roi", "t-tier", "t-moves", "opt-kpis", "insights"].forEach((id) => { $(id).innerHTML = ""; });
}

function showNotice(msg) { const n = $("notice"); n.hidden = !msg; n.textContent = msg || ""; }

async function loadOverview() {
  const [kpis, trend, regions] = await Promise.all([api("/api/kpis"), api("/api/trend"), api("/api/breakdown/region")]);
  const chg = kpis.trx_change_pct_6m;
  kpiCards("kpis", [
    { label: "Total Rx", value: fmt(kpis.total_trx), sub: chg === null ? "" : `${chg >= 0 ? "+" : ""}${chg}% vs prior 6M`, tone: chg >= 0 ? "good" : "bad" },
    { label: "Calls", value: fmt(kpis.total_calls) },
    { label: "Rx per call", value: fmt(kpis.trx_per_call, 2) },
    { label: "Active HCPs", value: fmt(kpis.active_hcps) },
    { label: "Samples / e-mails", value: `${fmt(kpis.total_samples)} / ${fmt(kpis.total_emails)}` },
  ]);
  const accent = cssVar("--accent"), amber = cssVar("--amber");
  draw("c-trend", {
    type: "bar",
    data: { labels: trend.map((r) => r.month), datasets: [
      { type: "line", label: "Calls", data: trend.map((r) => r.calls), borderColor: amber, backgroundColor: amber, yAxisID: "y2", tension: .3, pointRadius: 0, borderWidth: 2 },
      { label: "Rx", data: trend.map((r) => r.trx), backgroundColor: accent, borderRadius: 2, yAxisID: "y" } ] },
    options: { interaction: { mode: "index", intersect: false }, scales: { y: { title: { display: true, text: "Rx" } }, y2: { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "Calls" } } } },
  });
  draw("c-region", {
    type: "bar",
    data: { labels: regions.map((r) => r.name), datasets: [{ label: "Rx per call", data: regions.map((r) => r.trx_per_call), backgroundColor: accent, borderRadius: 2 }] },
    options: { plugins: { legend: { display: false } } },
  });
  const top = await api("/api/top-hcps", { limit: 10 });
  table("t-top", [
    { key: "name", label: "HCP" }, { key: "specialty", label: "Specialty" }, { key: "region", label: "Region" },
    { key: "tier", label: "Tier" }, { key: "trx", label: "Rx", num: true, f: (v) => fmt(v) }, { key: "calls", label: "Calls", num: true, f: (v) => fmt(v) },
  ], top);
}

async function loadModel() {
  const { model, roi } = await api("/api/model");
  const accent = cssVar("--accent"), amber = cssVar("--amber");
  const tiers = Object.entries(model.tier_beta).sort();
  draw("c-elast", {
    type: "bar",
    data: { labels: tiers.map(([t]) => `Tier ${t}`), datasets: [{ label: "Elasticity", data: tiers.map(([, b]) => b), backgroundColor: accent, borderRadius: 2 }] },
    options: { plugins: { legend: { display: false } } },
  });
  table("t-model", [
    { key: "term", label: "Term", f: (v) => v.replace(/_/g, " ") }, { key: "coef", label: "Coef", num: true, f: (v) => fmt(v, 3) },
    { key: "t", label: "t-stat", num: true, f: (v) => fmt(v, 1) },
    { key: "ci_low", label: "95% CI", num: true, f: (_, r) => `${fmt(r.ci_low, 3)} to ${fmt(r.ci_high, 3)}` },
  ], model.terms);
  draw("c-roi", {
    type: "bar",
    data: { labels: roi.map((r) => `${r.channel} ${r.scope === "All" ? "" : "(" + r.scope + ")"}`.trim()), datasets: [{ label: "ROI (x)", data: roi.map((r) => r.roi), backgroundColor: roi.map((r) => (r.roi >= 1 ? accent : cssVar("--bad"))), borderRadius: 2 }] },
    options: { indexAxis: "y", plugins: { legend: { display: false } } },
  });
  table("t-roi", [
    { key: "channel", label: "Channel" }, { key: "scope", label: "Scope" },
    { key: "incr_trx_per_unit", label: "Rx / unit", num: true, f: (v) => fmt(v, 3) },
    { key: "cost_per_unit", label: "Cost", num: true, f: money }, { key: "roi", label: "ROI", num: true, f: (v) => `${fmt(v, 2)}x` },
  ], roi);
  $("insights").dataset.ready = "1";
}

async function loadOptimizer() {
  const pct = Number($("budget").value);
  $("budget-val").textContent = `${pct > 0 ? "+" : ""}${pct}%`;
  const opt = await api("/api/optimize", { budget_change_pct: pct });
  const s = opt.summary;
  kpiCards("opt-kpis", [
    { label: "Calls / month", value: `${fmt(s.current_calls)} → ${fmt(s.recommended_calls)}` },
    { label: "Expected Rx", value: `${fmt(s.current_trx)} → ${fmt(s.expected_trx)}`, sub: s.uplift_pct === null ? "" : `${s.uplift_pct >= 0 ? "+" : ""}${s.uplift_pct}%`, tone: s.uplift_pct >= 0 ? "good" : "bad" },
    { label: "Incremental revenue", value: money(s.incremental_revenue) },
    { label: "Call cost change", value: money(s.call_cost_change) },
    { label: "Net value / month", value: money(s.net_value), tone: s.net_value >= 0 ? "good" : "bad" },
  ]);
  table("t-tier", [
    { key: "tier", label: "Tier" }, { key: "hcps", label: "HCPs", num: true, f: (v) => fmt(v) },
    { key: "current_calls", label: "Calls now", num: true, f: (v) => fmt(v, 0) }, { key: "recommended_calls", label: "Recommended", num: true, f: (v) => fmt(v) },
    { key: "trx_current", label: "Rx now", num: true, f: (v) => fmt(v, 0) }, { key: "trx_new", label: "Rx expected", num: true, f: (v) => fmt(v, 0) },
  ], opt.by_tier);
  table("t-moves", [
    { key: "hcp_id", label: "HCP" }, { key: "tier", label: "Tier" }, { key: "region", label: "Region" },
    { key: "current_calls", label: "Now", num: true, f: (v) => fmt(v, 1) }, { key: "recommended_calls", label: "Plan", num: true, f: (v) => fmt(v) },
    { key: "delta_trx", label: "Δ Rx", num: true, f: (v) => fmt(v, 2) },
  ], opt.top_moves);
}

async function loadInsights() {
  const pct = Number($("budget").value);
  const { insights } = await api("/api/insights", { budget_change_pct: pct });
  const ul = $("insights"); ul.innerHTML = "";
  insights.forEach((t) => { const li = document.createElement("li"); li.textContent = t; ul.appendChild(li); });
}

function updateDownloads() {
  const p = filterParams(); p.set("budget_change_pct", $("budget").value);
  $("dl-xlsx").href = `/api/export/xlsx?${p}`;
  $("dl-pptx").href = `/api/export/pptx?${p}`;
}

async function refresh() {
  document.querySelector("main").classList.add("loading");
  showNotice("");
  updateDownloads();
  try {
    await loadOverview();
    try { await Promise.all([loadModel(), loadOptimizer(), loadInsights()]); }
    catch (e) { if (e.status === 422) { clearModelPanels(); showNotice(e.message); } else throw e; }
  } catch (e) {
    showNotice(`Could not load data: ${e.message}`);
  } finally {
    document.querySelector("main").classList.remove("loading");
  }
}

let optTimer;
function init() {
  const saved = (() => { try { return localStorage.getItem("theme"); } catch (_) { return null; } })();
  if (saved) document.documentElement.dataset.theme = saved;
  else if (window.matchMedia("(prefers-color-scheme: dark)").matches) document.documentElement.dataset.theme = "dark";

  fetch("/api/meta").then((r) => r.json()).then((m) => {
    meta = m;
    const months = monthLabels(m.min_month, m.max_month);
    fillSelect("f-region", m.regions, "All regions");
    fillSelect("f-specialty", m.specialties, "All specialties");
    fillSelect("f-tier", m.tiers, "All tiers");
    fillSelect("f-start", months, "Earliest");
    fillSelect("f-end", months, "Latest");
    $("budget").min = -30; $("budget").max = 30;
    Object.values(FILTER_IDS).forEach((id) => { enhanceSelect($(id)); $(id).addEventListener("change", refresh); });
    $("reset").addEventListener("click", () => { Object.values(FILTER_IDS).forEach((id) => ($(id).value = "")); syncSelects(); $("budget").value = 0; refresh(); });
    $("budget").addEventListener("input", () => {
      $("budget-val").textContent = `${$("budget").value > 0 ? "+" : ""}${$("budget").value}%`;
      clearTimeout(optTimer);
      optTimer = setTimeout(() => { updateDownloads(); loadOptimizer().catch((e) => showNotice(e.message)); loadInsights().catch(() => {}); }, 200);
    });
    refresh();
  }).catch((e) => showNotice(`Could not load metadata: ${e.message}`));

  $("theme").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (_) { /* ignore */ }
    if (meta) refresh();
  });
}

document.addEventListener("DOMContentLoaded", init);
