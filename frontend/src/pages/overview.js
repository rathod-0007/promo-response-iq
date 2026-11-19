import { $, cssVar, draw, fmt, kpiCards, showNotice, signed, table } from "../ui.js";
import { T, activeDimensions, channelActive, state, tierName } from "../state.js";
import { api, dimensionColumns } from "./common.js";

export async function load() {
  const dims = activeDimensions();
  const by = dims.find((d) => d.key === "region") || dims[0];
  const [kpis, trend, top, breakdown] = await Promise.all([
    api("/api/kpis"), api("/api/trend"), api("/api/top-hcps", { limit: 10 }), by ? api(`/api/breakdown/${by.key}`) : null,
  ]);
  const chg = kpis.trx_change_pct_6m;
  kpiCards("kpis", [
    { label: T("Total {metric}"), value: fmt(kpis.total_trx), sub: chg === null ? "" : `${signed(chg)}% vs prior 6M`, tone: chg >= 0 ? "good" : "bad" },
    { label: T("{primary}"), value: fmt(kpis.total_calls) },
    { label: T("{metric} per {unit}"), value: fmt(kpis.trx_per_call, 2) },
    { label: T("Active {entities}"), value: fmt(kpis.active_hcps) },
    channelActive("samples") && { label: T("{second}"), value: fmt(kpis.total_samples) },
    channelActive("emails") && { label: T("{third}"), value: fmt(kpis.total_emails) },
  ]);

  const accent = cssVar("--accent"), amber = cssVar("--amber");
  draw("c-trend", {
    type: "bar",
    data: {
      labels: trend.map((r) => r.month),
      datasets: [
        { type: "line", label: T("{primary}"), data: trend.map((r) => r.calls), borderColor: amber, backgroundColor: amber, yAxisID: "y2", tension: 0.3, pointRadius: 0, borderWidth: 2 },
        { label: T("{metric}"), data: trend.map((r) => r.trx), backgroundColor: accent, borderRadius: 2, yAxisID: "y" },
      ],
    },
    options: {
      interaction: { mode: "index", intersect: false },
      scales: { y: { title: { display: true, text: T("{metric}") } }, y2: { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: T("{primary}") } } },
    },
  });

  $("card-breakdown").hidden = !by;
  if (by) {
    $("breakdown-title").textContent = T(`{metric} per {unit} by ${by.label.toLowerCase()}`);
    draw("c-region", {
      type: "bar",
      data: {
        labels: breakdown.map((r) => (by.key === "tier" ? tierName(r.name) : r.name)),
        datasets: [{ label: T("{metric} per {unit}"), data: breakdown.map((r) => r.trx_per_call), backgroundColor: accent, borderRadius: 2 }],
      },
      options: { plugins: { legend: { display: false } } },
    });
  }

  table("t-top", [
    { key: "name", label: T("{entity}") }, ...dimensionColumns(),
    { key: "trx", label: T("{metric}"), num: true, f: (v) => fmt(v) }, { key: "calls", label: T("{primary}"), num: true, f: (v) => fmt(v) },
  ], top, { empty: T("No {entities} for these filters") });

  loadInsights().catch((e) => showNotice(`Could not load insights: ${e.message}`));   // slow (runs every engine): do not block the page on it
}

async function loadInsights() {
  try {
    const { insights } = await api("/api/insights", { budget_change_pct: state.budget });
    const ol = $("insights");
    ol.innerHTML = "";
    insights.forEach((t) => { const li = document.createElement("li"); li.textContent = t; ol.appendChild(li); });
  } catch (e) {
    $("insights").innerHTML = "";
    if (e.status === 422) showNotice(e.message); else throw e;
  }
}
