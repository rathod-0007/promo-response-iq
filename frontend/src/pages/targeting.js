import { $, cssVar, draw, el, fmt, kpiCards, table } from "../ui.js";
import { T } from "../state.js";
import { api, dimensionColumns, notice } from "./common.js";

export async function load() {
  const t = await api("/api/targeting");
  if (!t.deciles.length) throw notice(T("No {entities} match the selected filters."));
  const s = t.summary, accent = cssVar("--accent"), amber = cssVar("--amber");
  kpiCards("tg-kpis", [
    { label: T(`Top ${s.high_volume_deciles} deciles: share of {metric}`), value: `${fmt(s.top_rx_share_pct, 1)}%` },
    { label: T(`Top ${s.high_volume_deciles} deciles: share of {primary_l}`), value: `${fmt(s.top_call_share_pct, 1)}%` },
    { label: "Alignment score", value: `${fmt(s.alignment_score_pct, 1)}%`, sub: T("100% = {primary_l} follow {metric} exactly") },
    { label: T("{entities} analysed"), value: fmt(s.hcps) },
  ]);
  draw("c-deciles", {
    type: "bar",
    data: {
      labels: t.deciles.map((d) => `D${d.decile}`),
      datasets: [
        { label: T("Share of {metric} %"), data: t.deciles.map((d) => d.rx_share_pct), backgroundColor: accent, borderRadius: 2 },
        { label: T("Share of {primary_l} %"), data: t.deciles.map((d) => d.call_share_pct), backgroundColor: amber, borderRadius: 2 },
      ],
    },
    options: { interaction: { mode: "index", intersect: false } },
  });
  table("t-deciles", [
    { key: "decile", label: "Decile" }, { key: "hcps", label: T("{entities}"), num: true, f: (v) => fmt(v) },
    { key: "rx_share_pct", label: T("{metric} %"), num: true, f: (v) => fmt(v, 1) }, { key: "call_share_pct", label: T("{primary} %"), num: true, f: (v) => fmt(v, 1) },
    { key: "trx_per_call", label: T("{metric} / {unit}"), num: true, f: (v) => fmt(v, 2) }, { key: "call_index", label: "Index", num: true, f: (v) => fmt(v, 2) },
    { key: "action", label: "Action", cell: (td, v) => td.appendChild(el("span", { class: `chip ${/^Under/.test(v) ? "warn" : /^Over/.test(v) ? "bad" : "ok"}`, text: v })) },
  ], t.deciles);

  const note = $("tg-note");
  note.hidden = !t.segments_note;
  note.textContent = t.segments_note ? `Segmentation unavailable: ${t.segments_note}` : "";
  table("t-segments", [
    { key: "segment", label: "Segment" }, { key: "hcps", label: T("{entities}"), num: true, f: (v) => fmt(v) },
    { key: "rx_share_pct", label: T("{metric} %"), num: true, f: (v) => fmt(v, 1) }, { key: "call_share_pct", label: T("{primary} %"), num: true, f: (v) => fmt(v, 1) },
    { key: "calls_per_hcp", label: T("{primary} / {entity}"), num: true, f: (v) => fmt(v, 1) }, { key: "advice", label: "Recommended action" },
  ], t.segments || [], { empty: "Segments need enough data to fit the response model" });

  const cols = [
    { key: "name", label: T("{entity}") }, ...dimensionColumns(["tier", "region"]),
    { key: "decile", label: "Decile", num: true }, { key: "trx", label: T("{metric}"), num: true, f: (v) => fmt(v) }, { key: "calls", label: T("{primary}"), num: true, f: (v) => fmt(v) },
  ];
  table("t-under", cols, t.under_served, { empty: T("None: every top {entity_l} has at least the median {unit} level") });
  table("t-over", cols, t.over_served, { empty: T("None: no low-volume {entity_l} gets top-{entity_l} {unit} levels") });
}
