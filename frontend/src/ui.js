// UI building blocks shared by every page: formatting, tables, KPI strips, charts, searchable dropdowns, sliders.
import { Chart, registerables } from "chart.js";
import { FILTER_IDS, pluralize } from "./state.js";

Chart.register(...registerables);

export const $ = (id) => document.getElementById(id);
export const fmt = (n, d = 0) => (n === null || n === undefined || Number.isNaN(n) ? "n/a"
  : Number(n).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));
export const money = (n) => (n === null || n === undefined ? "n/a" : `${n < 0 ? "-" : ""}$${fmt(Math.abs(n))}`);
export const signed = (n) => `${n > 0 ? "+" : ""}${n}`;
export const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
export const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== false && v !== null && v !== undefined) node.setAttribute(k, v === true ? "" : v);
  }
  node.append(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

export function showNotice(msg) {
  const n = $("notice");
  n.hidden = !msg;
  n.textContent = msg || "";
}

/* ---------- tables and KPI strips ---------- */
export function table(id, cols, rows, opts = {}) {
  const t = $(id);
  if (!t.parentElement.classList.contains("tbl")) {   // every table scrolls inside its card instead of spilling into its neighbour
    const wrap = el("div", { class: "tbl" });
    t.replaceWith(wrap);
    wrap.appendChild(t);
  }
  t.innerHTML = "";
  const head = t.createTHead().insertRow();
  cols.forEach((c) => {
    const th = document.createElement("th");
    th.textContent = c.label;
    if (c.num) th.classList.add("num");
    if (opts.onSort && c.sort) {
      th.classList.add("sortable");
      th.tabIndex = 0;
      if (opts.sort && opts.sort.key === c.key) th.textContent = `${c.label} ${opts.sort.order === "asc" ? "↑" : "↓"}`;
      const go = () => opts.onSort(c.key);
      th.addEventListener("click", go);
      th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    }
    head.appendChild(th);
  });
  const body = t.createTBody();
  if (!rows.length) {
    const td = body.insertRow().insertCell();
    td.colSpan = cols.length;
    td.className = "empty";
    td.textContent = opts.empty || "No data";
    return;
  }
  rows.forEach((r) => {
    const tr = body.insertRow();
    cols.forEach((c) => {
      const td = tr.insertCell();
      if (c.cell) c.cell(td, r[c.key], r);              // custom cell (badges)
      else td.textContent = c.f ? c.f(r[c.key], r) : r[c.key];
      if (c.num) td.className = "num";
    });
  });
}

/** Pick a column count that gives balanced rows (6 cards -> 3 + 3, never 5 + 1) for the width available. */
function layoutKpis(box) {
  const n = box.children.length;
  if (!n) return;
  const maxCols = Math.max(1, Math.floor(box.clientWidth / 175));
  const rows = Math.ceil(n / maxCols);
  box.style.setProperty("--cols", Math.ceil(n / rows));
}

const kpiObserver = new ResizeObserver((entries) => entries.forEach((e) => layoutKpis(e.target)));

export function kpiCards(id, items) {
  const box = $(id);
  box.innerHTML = "";
  items.filter(Boolean).forEach((k) => {
    const card = el("div", { class: "kpi" }, el("span", { text: k.label }), el("strong", { text: k.value }));
    if (k.sub) card.append(el("em", { class: k.tone || "", text: k.sub }));
    box.appendChild(card);
  });
  layoutKpis(box);
  if (!box._observed) { kpiObserver.observe(box); box._observed = true; }
}

/* ---------- charts ---------- */
const charts = {};
export function destroyChart(id) { if (charts[id]) { charts[id].destroy(); delete charts[id]; } }

export function draw(id, config) {
  destroyChart(id);
  Chart.defaults.color = cssVar("--muted");
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 11;
  Chart.defaults.borderColor = cssVar("--rule");
  charts[id] = new Chart($(id), { ...config, options: { responsive: true, maintainAspectRatio: false, ...config.options } });
}

/** Clear everything a page rendered (used when the API says there is not enough data). */
export function clearPage(key) {
  const root = $(`page-${key}`);
  root.querySelectorAll("canvas").forEach((c) => destroyChart(c.id));
  root.querySelectorAll("table, .kpis, ol, dl").forEach((n) => { n.innerHTML = ""; });
}

/* ---------- selects ---------- */
/** Fill a <select>. `format` maps a value to the text shown (the value itself is unchanged). */
export function fillSelect(id, options, allLabel, selected = "", format = (v) => v) {
  const sel = $(id);
  sel.innerHTML = "";
  if (allLabel) sel.add(new Option(allLabel, ""));
  options.forEach((o) => sel.add(new Option(format(o), o)));
  sel.value = selected;
  if (sel._combo) sel._combo.rebuild();
}

export const allLabelFor = (label) => `All ${pluralize(label).toLowerCase()}`;

/**
 * Searchable dropdown layered over a native <select>, which stays the source of truth.
 * The label lives inside the control ("All offices", "From 2024-07"); a chevron marks it as a dropdown.
 * Long lists stay fast: at most LIMIT matches are drawn, the rest appear as you type.
 */
const LIMIT = 200;
const combos = [];
export function enhanceSelect(sel) {
  if (sel._combo) { sel._combo.rebuild(); return; }
  const wrap = el("div", { class: "combo" });
  sel.parentNode.insertBefore(wrap, sel);
  wrap.appendChild(sel);
  sel.classList.add("native");
  const label = el("span");
  const btn = el("button", { type: "button", class: "combo-btn", "aria-haspopup": "listbox", "aria-expanded": "false", "aria-label": sel.getAttribute("aria-label") || "" }, label, el("i", { class: "caret" }));
  const search = el("input", { type: "search", placeholder: "Search...", "aria-label": "Search options" });
  const list = el("ul", { role: "listbox" });
  const empty = el("div", { class: "combo-empty", text: "No matches", hidden: true });
  const more = el("div", { class: "combo-more", hidden: true });
  const pop = el("div", { class: "combo-pop", hidden: true }, search, list, empty, more);
  wrap.append(btn, pop);
  let options = [];
  let active = 0;

  const items = () => [...list.children];
  const sync = () => {
    const o = sel.options[sel.selectedIndex];
    label.textContent = o ? o.text : "";
    items().forEach((li) => li.classList.toggle("sel", li.dataset.value === sel.value));
  };
  const setActive = (i) => {
    const li = items();
    active = Math.max(0, Math.min(i, li.length - 1));
    li.forEach((n) => n.classList.remove("act"));
    if (li[active]) { li[active].classList.add("act"); li[active].scrollIntoView({ block: "nearest" }); }
  };
  const render = () => {
    const q = search.value.trim().toLowerCase();
    const matches = options.filter((o) => o.text.toLowerCase().includes(q));
    list.replaceChildren(...matches.slice(0, LIMIT).map((o) => {
      const li = el("li", { role: "option", "data-value": o.value, text: o.text });
      li.addEventListener("click", () => choose(o.value));
      return li;
    }));
    empty.hidden = matches.length > 0;
    more.hidden = matches.length <= LIMIT;
    more.textContent = `Showing ${LIMIT} of ${matches.length.toLocaleString()}. Keep typing to narrow the list.`;
    sync();
    setActive(0);
  };
  const close = () => { pop.hidden = true; btn.setAttribute("aria-expanded", "false"); };
  const open = () => { combos.forEach((c) => c.close()); pop.hidden = false; btn.setAttribute("aria-expanded", "true"); search.value = ""; render(); search.focus(); };
  const choose = (v) => { sel.value = v; sync(); close(); sel.dispatchEvent(new Event("change")); btn.focus(); };
  const rebuild = () => { options = [...sel.options].map((o) => ({ value: o.value, text: o.text })); render(); };
  btn.addEventListener("click", () => (pop.hidden ? open() : close()));
  search.addEventListener("input", render);
  search.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
    else if (e.key === "Enter") { e.preventDefault(); const a = items()[active]; if (a) choose(a.dataset.value); }
    else if (e.key === "Escape") { close(); btn.focus(); }
  });
  document.addEventListener("click", (e) => { if (!wrap.contains(e.target)) close(); });
  sel._combo = { rebuild, sync, close };
  combos.push(sel._combo);
  rebuild();
}
export const syncSelects = () => combos.forEach((c) => c.sync());

export function filterParams() {
  const p = {};
  for (const [k, id] of Object.entries(FILTER_IDS)) { const v = $(id).value; if (v) p[k] = v; }
  return p;
}

/* ---------- sliders: the filled part of the track follows the value ---------- */
export function paintRange(input) {
  const min = Number(input.min || 0), max = Number(input.max || 100), v = Number(input.value);
  input.style.setProperty("--pct", `${max === min ? 0 : ((v - min) / (max - min)) * 100}%`);
}
export function bindRange(input, onInput) {
  paintRange(input);
  input.addEventListener("input", () => { paintRange(input); if (onInput) onInput(); });
}
