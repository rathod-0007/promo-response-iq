import { $, clearPage, fmt, kpiCards, money, paintRange, signed, table } from "../ui.js";
import { T, state, tierName } from "../state.js";
import { api, dimensionColumns } from "./common.js";

export function labelBudget() {
  const v = Number($("budget").value);
  $("budget-val").textContent = `${signed(v)}%`;
}

export async function load() {
  const pct = state.budget;
  $("budget").value = pct;
  paintRange($("budget"));
  labelBudget();
  clearPage("optimizer");
  const opt = await api("/api/optimize", { budget_change_pct: pct });
  const s = opt.summary;
  kpiCards("opt-kpis", [
    { label: T("{primary} / month"), value: `${fmt(s.current_calls)} → ${fmt(s.recommended_calls)}` },
    { label: T("Expected {metric}"), value: `${fmt(s.current_trx)} → ${fmt(s.expected_trx)}`, sub: s.uplift_pct === null ? "" : `${signed(s.uplift_pct)}%`, tone: s.uplift_pct >= 0 ? "good" : "bad" },
    { label: "Incremental revenue", value: money(s.incremental_revenue) },
    { label: T("{primary} cost change"), value: money(s.call_cost_change) },
    { label: "Net value / month", value: money(s.net_value), tone: s.net_value >= 0 ? "good" : "bad" },
  ]);
  table("t-tier", [
    { key: "tier", label: T("{tier}"), f: (v) => tierName(v) }, { key: "hcps", label: T("{entities}"), num: true, f: (v) => fmt(v) },
    { key: "current_calls", label: T("{primary} now"), num: true, f: (v) => fmt(v, 0) }, { key: "recommended_calls", label: "Recommended", num: true, f: (v) => fmt(v) },
    { key: "trx_current", label: T("{metric} now"), num: true, f: (v) => fmt(v, 0) }, { key: "trx_new", label: T("{metric} expected"), num: true, f: (v) => fmt(v, 0) },
  ], opt.by_tier);
  table("t-moves", [
    { key: "name", label: T("{entity}") }, ...dimensionColumns(["tier", "region"]),
    { key: "current_calls", label: "Now", num: true, f: (v) => fmt(v, 1) }, { key: "recommended_calls", label: "Plan", num: true, f: (v) => fmt(v) },
    { key: "delta_trx", label: T("Δ {metric}"), num: true, f: (v) => fmt(v, 2) },
  ], opt.top_moves);
}
