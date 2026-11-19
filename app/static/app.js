"use strict";

const $ = (id) => document.getElementById(id);
const FILTER_IDS = { region: "f-region", specialty: "f-specialty", tier: "f-tier", start: "f-start", end: "f-end" };
const charts = {};
let meta = null;
const state = { budget: 0, page: "overview", hcp: { q: "", sort: "trx", order: "desc", page: 1, size: 15 } };

const fmt = (n, d = 0) => (n === null || n === undefined ? "n/a" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));
const money = (n) => (n === null || n === undefined ? "n/a" : (n < 0 ? "-$" : "$") + fmt(Math.abs(n)));
const signed = (n) => `${n > 0 ? "+" : ""}${n}`;

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

/* ---------- small UI helpers ---------- */
function table(id, cols, rows, opts = {}) {
  const t = $(id); t.innerHTML = "";
  const head = t.createTHead().insertRow();
  cols.forEach((c) => {
    const th = document.createElement("th"); th.textContent = c.label;
    if (c.num) th.classList.add("num");
    if (opts.onSort && c.sort) {
      th.classList.add("sortable"); th.tabIndex = 0;
      if (opts.sort && opts.sort.key === c.key) th.textContent = `${c.label} ${opts.sort.order === "asc" ? "↑" : "↓"}`;
      const go = () => opts.onSort(c.key);
      th.addEventListener("click", go);
      th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    }
    head.appendChild(th);
  });
  const body = t.createTBody();
  if (!rows.length) {
    const td = body.insertRow().insertCell(); td.colSpan = cols.length; td.className = "empty"; td.textContent = opts.empty || "No data";
    return;
  }
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
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 11;
  Chart.defaults.borderColor = cssVar("--rule");
  charts[id] = new Chart($(id), { ...config, options: { responsive: true, maintainAspectRatio: false, ...config.options } });
}

function destroyChart(id) { if (charts[id]) { charts[id].destroy(); delete charts[id]; } }

function clearModelPanels() {
  ["c-elast", "c-roi"].forEach(destroyChart);
  ["t-model", "t-roi", "t-decay", "t-tier", "t-moves", "opt-kpis", "insights"].forEach((id) => { $(id).innerHTML = ""; });
}

function showNotice(msg) { const n = $("notice"); n.hidden = !msg; n.textContent = msg || ""; }

/* ---------- page loaders ---------- */
async function loadOverview() {
  const [kpis, trend, regions, top] = await Promise.all([
    api("/api/kpis"), api("/api/trend"), api("/api/breakdown/region"), api("/api/top-hcps", { limit: 10 })]);
  const chg = kpis.trx_change_pct_6m;
  kpiCards("kpis", [
    { label: "Total Rx", value: fmt(kpis.total_trx), sub: chg === null ? "" : `${signed(chg)}% vs prior 6M`, tone: chg >= 0 ? "good" : "bad" },
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
      { label: "Rx", data: trend.map((r) => r.trx), backgroundColor: accent, borderRadius: 2, yAxisID: "y" }] },
    options: { interaction: { mode: "index", intersect: false }, scales: { y: { title: { display: true, text: "Rx" } }, y2: { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "Calls" } } } },
  });
  draw("c-region", {
    type: "bar",
    data: { labels: regions.map((r) => r.name), datasets: [{ label: "Rx per call", data: regions.map((r) => r.trx_per_call), backgroundColor: accent, borderRadius: 2 }] },
    options: { plugins: { legend: { display: false } } },
  });
  table("t-top", [
    { key: "name", label: "HCP" }, { key: "specialty", label: "Specialty" }, { key: "region", label: "Region" },
    { key: "tier", label: "Tier" }, { key: "trx", label: "Rx", num: true, f: (v) => fmt(v) }, { key: "calls", label: "Calls", num: true, f: (v) => fmt(v) },
  ], top, { empty: "No prescribers for these filters" });
  try {
    const { insights } = await api("/api/insights", { budget_change_pct: state.budget });
    const ul = $("insights"); ul.innerHTML = "";
    insights.forEach((t) => { const li = document.createElement("li"); li.textContent = t; ul.appendChild(li); });
  } catch (e) {
    $("insights").innerHTML = "";
    if (e.status === 422) showNotice(e.message); else throw e;
  }
}

async function loadModel() {
  clearModelPanels();
  const { model, roi } = await api("/api/model");
  const accent = cssVar("--accent");
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
  const decays = Object.entries(model.decay_scores).map(([d, r2]) => ({ decay: Number(d), r2, best: Number(d) === model.decay }));
  table("t-decay", [
    { key: "decay", label: "Monthly decay", f: (v) => `${fmt(v * 100)}%` },
    { key: "r2", label: "Within-HCP R²", num: true, f: (v) => fmt(v, 4) },
    { key: "best", label: "Selected", f: (v) => (v ? "✓ best fit" : "") },
  ], decays);
}

async function loadOptimizer() {
  const pct = state.budget;
  $("budget").value = pct;
  $("budget-val").textContent = `${signed(pct)}%`;
  clearModelPanels();
  const opt = await api("/api/optimize", { budget_change_pct: pct });
  const s = opt.summary;
  kpiCards("opt-kpis", [
    { label: "Calls / month", value: `${fmt(s.current_calls)} → ${fmt(s.recommended_calls)}` },
    { label: "Expected Rx", value: `${fmt(s.current_trx)} → ${fmt(s.expected_trx)}`, sub: s.uplift_pct === null ? "" : `${signed(s.uplift_pct)}%`, tone: s.uplift_pct >= 0 ? "good" : "bad" },
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

async function loadExplorer() {
  const h = state.hcp;
  const res = await api("/api/hcps", { q: h.q, sort: h.sort, order: h.order, page: h.page, page_size: h.size });
  const pages = Math.max(1, Math.ceil(res.total / res.page_size));
  if (h.page > pages) { h.page = pages; return loadExplorer(); }
  const from = res.total ? (res.page - 1) * res.page_size + 1 : 0;
  const to = Math.min(res.total, res.page * res.page_size);
  $("hcp-count").textContent = `${fmt(res.total)} HCPs`;
  $("pg-info").textContent = res.total ? `${fmt(from)}–${fmt(to)} of ${fmt(res.total)}` : "No results";
  $("pg-prev").disabled = res.page <= 1;
  $("pg-next").disabled = res.page >= pages;
  const onSort = (key) => { h.order = h.sort === key && h.order === "desc" ? "asc" : "desc"; h.sort = key; h.page = 1; load(); };
  table("t-hcps", [
    { key: "name", label: "HCP", sort: true }, { key: "specialty", label: "Specialty", sort: true }, { key: "region", label: "Region", sort: true },
    { key: "tier", label: "Tier", sort: true }, { key: "trx", label: "Rx", num: true, sort: true, f: (v) => fmt(v) },
    { key: "calls", label: "Calls", num: true, sort: true, f: (v) => fmt(v) }, { key: "trx_per_call", label: "Rx / call", num: true, sort: true, f: (v) => fmt(v, 2) },
  ], res.rows, { sort: { key: h.sort, order: h.order }, onSort, empty: "No HCPs match your search" });
}

async function loadData() {
  const [info, health] = await Promise.all([fetch("/api/data-info").then((r) => r.json()), fetch("/api/health").then((r) => r.json())]);
  const rows = [
    ["Database", `${health.database} (${health.status})`], ["Schema", info.schema], ["Source", info.source],
    ["Loaded at", new Date(info.loaded_at).toLocaleString()], ["Loads so far", fmt(info.loads)],
    ["HCPs", fmt(info.hcps)], ["Activity rows", fmt(info.activity_rows)], ["Rx rows", fmt(info.rx_rows)],
    ["Period", `${info.first_month} to ${info.last_month}`],
  ];
  const dl = $("data-info"); dl.innerHTML = "";
  rows.forEach(([k, v]) => { const dt = document.createElement("dt"), dd = document.createElement("dd"); dt.textContent = k; dd.textContent = v; dl.append(dt, dd); });
}

/* ---------- router ---------- */
const PAGES = {
  overview: { title: "Overview", sub: "Performance at a glance", load: loadOverview, filters: true },
  model: { title: "Response model", sub: "How strongly each channel moves prescriptions", load: loadModel, filters: true },
  optimizer: { title: "Optimizer", sub: "What-if call allocation", load: loadOptimizer, filters: true },
  explorer: { title: "HCP explorer", sub: "Search, sort and page through every prescriber", load: loadExplorer, filters: true },
  data: { title: "Data & reports", sub: "Warehouse status, exports and imports", load: loadData, filters: false },
};

function currentPage() {
  const key = location.hash.replace(/^#\/?/, "");
  return PAGES[key] ? key : "overview";
}

function updateDownloads() {
  const p = filterParams(); p.set("budget_change_pct", state.budget);
  ["dl-xlsx", "dl-xlsx-2"].forEach((id) => { $(id).href = `/api/export/xlsx?${p}`; });
  ["dl-pptx", "dl-pptx-2"].forEach((id) => { $(id).href = `/api/export/pptx?${p}`; });
}

async function load() {
  const key = state.page;
  const main = document.querySelector("main");
  main.classList.add("loading"); showNotice(""); updateDownloads();
  try {
    await PAGES[key].load();
  } catch (e) {
    if (e.status === 422) { clearModelPanels(); showNotice(e.message); } else showNotice(`Could not load data: ${e.message}`);
  } finally {
    main.classList.remove("loading");
  }
}

function openMenu() { $("sidebar").classList.add("open"); $("scrim").classList.add("show"); }
function closeMenu() { $("sidebar").classList.remove("open"); $("scrim").classList.remove("show"); }

function show() {
  const key = currentPage();
  state.page = key;
  Object.keys(PAGES).forEach((k) => { $(`page-${k}`).hidden = k !== key; });
  document.querySelectorAll("#nav a").forEach((a) => {
    const on = a.dataset.page === key;
    a.classList.toggle("active", on);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  $("page-title").textContent = PAGES[key].title;
  $("page-sub").textContent = PAGES[key].sub;
  document.title = `${PAGES[key].title} · PromoResponseIQ`;
  $("filters").hidden = !PAGES[key].filters;
  closeMenu();
  window.scrollTo(0, 0);
  load();
}

function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

function init() {
  const saved = (() => { try { return localStorage.getItem("theme"); } catch (_) { return null; } })();
  if (saved) document.documentElement.dataset.theme = saved;
  else if (window.matchMedia("(prefers-color-scheme: dark)").matches) document.documentElement.dataset.theme = "dark";

  $("theme").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (_) { /* ignore */ }
    if (meta) load();
  });
  $("menu").addEventListener("click", openMenu);
  $("scrim").addEventListener("click", closeMenu);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
  window.addEventListener("hashchange", () => { if (meta) show(); });

  fetch("/api/meta").then((r) => r.json()).then((m) => {
    meta = m;
    const months = monthLabels(m.min_month, m.max_month);
    fillSelect("f-region", m.regions, "All regions");
    fillSelect("f-specialty", m.specialties, "All specialties");
    fillSelect("f-tier", m.tiers, "All tiers");
    fillSelect("f-start", months, "Earliest");
    fillSelect("f-end", months, "Latest");
    Object.values(FILTER_IDS).forEach((id) => {
      enhanceSelect($(id));
      $(id).addEventListener("change", () => { state.hcp.page = 1; load(); });
    });
    $("reset").addEventListener("click", () => {
      Object.values(FILTER_IDS).forEach((id) => ($(id).value = ""));
      syncSelects();
      state.budget = 0; state.hcp.page = 1; load();
    });
    $("budget").addEventListener("input", () => { $("budget-val").textContent = `${signed(Number($("budget").value))}%`; });
    $("budget").addEventListener("change", () => { state.budget = Number($("budget").value); load(); });
    $("hcp-q").addEventListener("input", debounce(() => { state.hcp.q = $("hcp-q").value.trim(); state.hcp.page = 1; load(); }, 250));
    $("pg-prev").addEventListener("click", () => { state.hcp.page = Math.max(1, state.hcp.page - 1); load(); });
    $("pg-next").addEventListener("click", () => { state.hcp.page += 1; load(); });
    show();
  }).catch((e) => showNotice(`Could not load metadata: ${e.message}`));
}

document.addEventListener("DOMContentLoaded", init);
