import "@fontsource-variable/montserrat";   // same typeface as the IFMS platform (self-hosted)
import "./styles.css";

import { getJSON, url } from "./api.js";
import { $, allLabelFor, bindRange, clearPage, debounce, enhanceSelect, fillSelect, filterParams, showNotice, syncSelects } from "./ui.js";
import { FILTER_IDS, T, applyLabels, dimensions, setProfile, state, tierName } from "./state.js";
import * as overview from "./pages/overview.js";
import * as model from "./pages/model.js";
import * as optimizer from "./pages/optimizer.js";
import * as targeting from "./pages/targeting.js";
import * as incentive from "./pages/incentive.js";
import * as explorer from "./pages/explorer.js";
import * as data from "./pages/data.js";
import * as bi from "./pages/bi.js";

const PAGES = {
  overview: { title: () => "Overview", sub: () => T("Performance at a glance"), load: overview.load, filters: true },
  model: { title: () => "Response model", sub: () => T("How strongly each channel moves {metric}"), load: model.load, filters: true },
  optimizer: { title: () => "Optimizer", sub: () => "What-if allocation of the main promotion channel", load: optimizer.load, filters: true },
  targeting: { title: () => "Targeting", sub: () => T("Is {primary_l} activity aligned with {metric} potential?"), load: targeting.load, filters: true },
  incentive: {
    title: () => "Incentive compensation", sub: () => T("Quota attainment, payout and plan cost by {territory_l}"), load: incentive.load, filters: true,
  },
  explorer: { title: () => T("{entity} explorer"), sub: () => T("Search, sort and page through every {entity_l}"), load: explorer.load, filters: true },
  data: { title: () => "Data & reports", sub: () => "Current data set, uploads, history and data dictionary", load: data.load, filters: false },
  bi: { title: () => "BI connections", sub: () => "Use this data in Tableau, Power BI or Sisense", load: bi.load, filters: false },
};
const loaded = new Set();            // pages that have shown data at least once
const DIM_LISTS = { region: "regions", specialty: "specialties", tier: "tiers" };

/* ---------- data set labels, filters ---------- */
function monthLabels(lo, hi) {
  const out = [];
  let [y, m] = lo.split("-").map(Number);
  const [hy, hm] = hi.split("-").map(Number);
  while (y < hy || (y === hy && m <= hm)) { out.push(`${y}-${String(m).padStart(2, "0")}`); m++; if (m > 12) { m = 1; y++; } }
  return out;
}

function renderFilters() {
  const m = state.meta;
  dimensions().forEach((d) => {
    const field = document.querySelector(`.field[data-dim="${d.key}"]`);
    field.hidden = !d.active;
    $(FILTER_IDS[d.key]).setAttribute("aria-label", d.label);
    fillSelect(FILTER_IDS[d.key], m[DIM_LISTS[d.key]], allLabelFor(d.label), "", d.key === "tier" ? tierName : undefined);
  });
  const months = monthLabels(m.min_month, m.max_month);
  fillSelect(FILTER_IDS.start, months, "From: earliest month", "", (v) => `From ${v}`);
  fillSelect(FILTER_IDS.end, months, "To: latest month", "", (v) => `To ${v}`);
}

async function loadMeta() {
  state.meta = await getJSON("/api/meta");
  setProfile(state.meta.profile);
  applyLabels();
  renderFilters();
  $("dataset-badge").textContent = state.meta.profile.kind === "synthetic" ? "Synthetic demo data" : state.meta.profile.name;
  document.querySelectorAll("#nav a").forEach((a) => { a.dataset.tip = a.querySelector(".nav-text").textContent; });
}

async function onDatasetChanged() {
  loaded.clear();
  state.budget = 0;
  state.hcp = { q: "", sort: "trx", order: "desc", page: 1, size: 15 };
  $("hcp-q").value = "";
  await loadMeta();
  incentive.resetPlan();
}

/* ---------- routing ---------- */
const currentPage = () => { const k = location.hash.replace(/^#\/?/, ""); return PAGES[k] ? k : "overview"; };

function updateDownloads() {
  const p = { ...filterParams(), budget_change_pct: state.budget };
  ["dl-xlsx", "dl-xlsx-2"].forEach((id) => { $(id).href = url("/api/export/xlsx", p); });
  ["dl-pptx", "dl-pptx-2"].forEach((id) => { $(id).href = url("/api/export/pptx", p); });
}

async function load() {
  const key = state.page;
  const main = document.querySelector("main");
  main.classList.add("loading");
  showNotice("");
  updateDownloads();
  try {
    await PAGES[key].load();
  } catch (e) {
    if (e.status === 422) { clearPage(key); showNotice(e.message); } else showNotice(`Could not load data: ${e.message}`);
  } finally {
    main.classList.remove("loading");
    loaded.add(key);
    $(`page-${key}`).classList.remove("pending");
    if (state.page === key) $("boot").hidden = true;
  }
}

const openMenu = () => { $("sidebar").classList.add("open"); $("scrim").classList.add("show"); };
const closeMenu = () => { $("sidebar").classList.remove("open"); $("scrim").classList.remove("show"); };

function show() {
  const key = currentPage();
  state.page = key;
  const page = PAGES[key];
  const first = !loaded.has(key);
  Object.keys(PAGES).forEach((k) => { $(`page-${k}`).hidden = k !== key; });
  $(`page-${key}`).classList.toggle("pending", first);
  $("boot").hidden = !first;
  document.querySelectorAll("#nav a").forEach((a) => {
    const on = a.dataset.page === key;
    a.classList.toggle("active", on);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  $("page-title").textContent = page.title();
  $("page-sub").textContent = page.sub();
  document.title = `${page.title()} · RxLift`;
  $("filters").hidden = !page.filters;
  closeMenu();
  window.scrollTo(0, 0);
  load();
}

/* ---------- chrome: theme, collapsible sidebar ---------- */
function initTheme() {
  const saved = (() => { try { return localStorage.getItem("theme"); } catch (_) { return null; } })();
  if (saved) document.documentElement.dataset.theme = saved;
  else if (window.matchMedia("(prefers-color-scheme: dark)").matches) document.documentElement.dataset.theme = "dark";
  $("theme").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (_) { /* private mode */ }
    if (state.meta) load();
  });
}

function initSidebar() {
  const shell = $("shell"), btn = $("collapse");
  const set = (collapsed) => {
    shell.classList.toggle("collapsed", collapsed);
    const label = collapsed ? "Expand sidebar" : "Collapse sidebar";
    btn.setAttribute("aria-label", label);
    btn.title = label;
    btn.setAttribute("aria-expanded", String(!collapsed));
    try { localStorage.setItem("sidebar", collapsed ? "collapsed" : "open"); } catch (_) { /* private mode */ }
    setTimeout(() => window.dispatchEvent(new Event("resize")), 260);   // let charts re-fit the new width
  };
  const saved = (() => { try { return localStorage.getItem("sidebar"); } catch (_) { return null; } })();
  shell.classList.toggle("collapsed", saved === "collapsed");
  btn.setAttribute("aria-expanded", String(saved !== "collapsed"));
  if (saved === "collapsed") { btn.title = "Expand sidebar"; btn.setAttribute("aria-label", "Expand sidebar"); }
  btn.addEventListener("click", () => set(!shell.classList.contains("collapsed")));
  $("menu").addEventListener("click", openMenu);
  $("scrim").addEventListener("click", closeMenu);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
}

/* ---------- start ---------- */
function bindControls() {
  Object.values(FILTER_IDS).forEach((id) => {
    enhanceSelect($(id));
    $(id).addEventListener("change", () => { state.hcp.page = 1; load(); });
  });
  $("reset").addEventListener("click", () => {
    Object.values(FILTER_IDS).forEach((id) => { $(id).value = ""; });
    syncSelects();
    state.budget = 0;
    state.hcp.page = 1;
    load();
  });
  bindRange($("budget"), optimizer.labelBudget);
  $("budget").addEventListener("change", () => { state.budget = Number($("budget").value); load(); });
  incentive.bindControls(() => { if (state.page === "incentive") load(); });
  enhanceSelect($("ic-quarter"));
  explorer.bindExplorer(() => load());
  $("hcp-q").addEventListener("input", debounce(() => { state.hcp.q = $("hcp-q").value.trim(); state.hcp.page = 1; load(); }, 250));
  $("pg-prev").addEventListener("click", () => { state.hcp.page = Math.max(1, state.hcp.page - 1); load(); });
  $("pg-next").addEventListener("click", () => { state.hcp.page += 1; load(); });
  data.bindUpload();
  data.bindData({ onDatasetChanged, goto: (p) => { location.hash = `#/${p}`; } });
  bi.bindBiControls();
  $("btn-template").href = url("/api/upload/template");
  window.addEventListener("hashchange", () => { if (state.meta) show(); });
}

async function init() {
  document.documentElement.classList.add("ready");   // the stylesheet is applied: reveal the page (see index.html)
  initTheme();
  initSidebar();
  bindControls();
  try {
    await loadMeta();
    incentive.resetPlan();
  } catch (e) {
    $("boot").hidden = true;
    showNotice(`Cannot reach the API (${e.message}). Start it with: uvicorn app.main:app --port 8000`);
    return;
  }
  show();
}

init();
