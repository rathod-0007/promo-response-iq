import { $, bindRange, cssVar, draw, fillSelect, fmt, kpiCards, money, paintRange, signed, table } from "../ui.js";
import { T, state } from "../state.js";
import { api, notice } from "./common.js";

/* Plan controls start from the config defaults (/api/meta) and are sent as per-request overrides. */
const SLIDERS = [
  { id: "ic-growth", min: -10, max: 30, value: (d) => d.quota_growth_pct },
  { id: "ic-threshold", min: 50, max: 95, value: (d) => Math.round(d.threshold_attainment * 100) },
  { id: "ic-accel", min: 0, max: 3, value: (d) => d.accelerator },
];

function labels() {
  $("ic-growth-val").textContent = `${signed(Number($("ic-growth").value))}%`;
  $("ic-threshold-val").textContent = `${$("ic-threshold").value}%`;
  $("ic-accel-val").textContent = `${Number($("ic-accel").value).toFixed(2)}x`;
}

export function resetPlan() {
  const d = state.meta.incentive;
  SLIDERS.forEach((s) => {
    const el = $(s.id), v = s.value(d);
    el.min = Math.min(s.min, v);
    el.max = Math.max(s.max, v);
    el.value = v;
    paintRange(el);
  });
  fillSelect("ic-quarter", [], "", "");
  labels();
}

export function bindControls(onChange) {
  SLIDERS.forEach((s) => {
    bindRange($(s.id), labels);
    $(s.id).addEventListener("change", onChange);
  });
  $("ic-quarter").addEventListener("change", onChange);
  $("ic-reset").addEventListener("click", () => { resetPlan(); onChange(); });
}

const params = () => {
  const p = {
    quota_growth_pct: Number($("ic-growth").value),
    threshold_attainment: Number($("ic-threshold").value) / 100,
    accelerator: Number($("ic-accel").value),
  };
  if ($("ic-quarter").value) p.quarter = $("ic-quarter").value;
  return p;
};

export async function load() {
  if (!state.profile.has_territories) {
    throw notice("No territory data is loaded. Map a territory column when you upload your data (Data & reports) to enable incentive compensation.");
  }
  labels();
  let res;
  try {
    res = await api("/api/incentive", params());
  } catch (e) {
    if (e.status === 422 && /not available/.test(e.message) && $("ic-quarter").value) { fillSelect("ic-quarter", [], "", ""); res = await api("/api/incentive", params()); }
    else throw e;
  }
  const s = res.summary, accent = cssVar("--accent"), bad = cssVar("--bad");
  fillSelect("ic-quarter", res.quarters, "", res.quarter, (q) => `Quarter ${q}`);
  kpiCards("ic-kpis", [
    { label: "Attainment vs quota", value: `${fmt(s.weighted_attainment_pct, 1)}%`, sub: T(`${s.territories} {territories_l} x ${s.quarters} quarters`) },
    { label: T("{territory}-quarters at quota"), value: `${fmt(s.pct_at_or_above_target, 1)}%`, sub: `${fmt(s.pct_below_threshold, 1)}% below payout threshold`, tone: s.pct_below_threshold > 0 ? "bad" : "good" },
    { label: "Total payout", value: money(s.total_payout), sub: `${fmt(s.payout_vs_target_pct, 1)}% of target incentive` },
    { label: "Cost of sales", value: s.cost_of_sales_pct === null ? "n/a" : `${fmt(s.cost_of_sales_pct, 2)}%`, sub: T("payout / {metric} revenue") },
  ]);
  draw("c-ic-hist", {
    type: "bar",
    data: { labels: res.histogram.map((b) => b.label), datasets: [{ label: T("{territory}-quarters"), data: res.histogram.map((b) => b.count), backgroundColor: res.histogram.map((b) => (b.below_threshold ? bad : accent)), borderRadius: 2 }] },
    options: { plugins: { legend: { display: false } } },
  });
  draw("c-ic-curve", {
    type: "line",
    data: { labels: res.curve.map((c) => `${c.attainment_pct}%`), datasets: [{ label: "Payout % of target", data: res.curve.map((c) => c.payout_pct), borderColor: accent, backgroundColor: accent, pointRadius: 0, borderWidth: 2 }] },
    options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { maxTicksLimit: 8 } } } },
  });
  table("t-ic-quarters", [
    { key: "quarter", label: "Quarter" }, { key: "territories", label: T("{territories}"), num: true, f: (v) => fmt(v) },
    { key: "attainment_pct", label: "Attainment", num: true, f: (v) => `${fmt(v, 1)}%` },
    { key: "pct_at_or_above_target", label: "At quota", num: true, f: (v) => `${fmt(v, 0)}%` }, { key: "total_payout", label: "Payout", num: true, f: money },
  ], res.by_quarter);
  $("ic-quarter-label").textContent = `${res.quarter}, ranked by attainment`;
  table("t-ic-terr", [
    { key: "territory", label: T("{territory}") }, { key: "rep_name", label: T("{rep}") },
    { key: "actual", label: T("{metric}"), num: true, f: (v) => fmt(v) }, { key: "quota", label: "Quota", num: true, f: (v) => fmt(v) },
    { key: "attainment_pct", label: "Attain.", num: true, f: (v) => `${fmt(v, 1)}%` }, { key: "payout_pct", label: "Payout %", num: true, f: (v) => `${fmt(v, 0)}%` },
    { key: "payout", label: "Payout", num: true, f: money },
  ], res.territories);
}
