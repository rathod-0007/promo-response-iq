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
  charts[id] = new Chart($(id), { ...config, options: { responsive: true, maintainAspectRatio: false, ...config.options } });
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
  const accent = cssVar("--accent"), accent2 = cssVar("--accent-2");
  draw("c-trend", {
    type: "bar",
    data: { labels: trend.map((r) => r.month), datasets: [
      { type: "line", label: "Calls", data: trend.map((r) => r.calls), borderColor: accent2, backgroundColor: accent2, yAxisID: "y2", tension: .3, pointRadius: 0, borderWidth: 2 },
      { label: "Rx", data: trend.map((r) => r.trx), backgroundColor: accent, borderRadius: 6, yAxisID: "y" } ] },
    options: { interaction: { mode: "index", intersect: false }, scales: { y: { title: { display: true, text: "Rx" } }, y2: { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "Calls" } } } },
  });
  draw("c-region", {
    type: "bar",
    data: { labels: regions.map((r) => r.name), datasets: [{ label: "Rx per call", data: regions.map((r) => r.trx_per_call), backgroundColor: accent2, borderRadius: 8 }] },
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
  const accent = cssVar("--accent"), accent2 = cssVar("--accent-2");
  const tiers = Object.entries(model.tier_beta).sort();
  draw("c-elast", {
    type: "bar",
    data: { labels: tiers.map(([t]) => `Tier ${t}`), datasets: [{ label: "Elasticity", data: tiers.map(([, b]) => b), backgroundColor: accent, borderRadius: 8 }] },
    options: { plugins: { legend: { display: false } } },
  });
  table("t-model", [
    { key: "term", label: "Term", f: (v) => v.replace(/_/g, " ") }, { key: "coef", label: "Coef", num: true, f: (v) => fmt(v, 3) },
    { key: "t", label: "t-stat", num: true, f: (v) => fmt(v, 1) },
    { key: "ci_low", label: "95% CI", num: true, f: (_, r) => `${fmt(r.ci_low, 3)} to ${fmt(r.ci_high, 3)}` },
  ], model.terms);
  draw("c-roi", {
    type: "bar",
    data: { labels: roi.map((r) => `${r.channel} ${r.scope === "All" ? "" : "(" + r.scope + ")"}`.trim()), datasets: [{ label: "ROI (x)", data: roi.map((r) => r.roi), backgroundColor: roi.map((r) => (r.roi >= 1 ? accent2 : cssVar("--bad"))), borderRadius: 8 }] },
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
    catch (e) { if (e.status === 422) showNotice(e.message); else throw e; }
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
    Object.values(FILTER_IDS).forEach((id) => $(id).addEventListener("change", refresh));
    $("reset").addEventListener("click", () => { Object.values(FILTER_IDS).forEach((id) => ($(id).value = "")); $("budget").value = 0; refresh(); });
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
