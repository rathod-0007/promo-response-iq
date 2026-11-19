import { cssVar, clearPage, draw, fmt, money, table } from "../ui.js";
import { T, channelLabel, state, termLabel, tierName } from "../state.js";
import { api } from "./common.js";

export async function load() {
  clearPage("model");
  const { model, roi } = await api("/api/model");
  const accent = cssVar("--accent");
  const tiers = Object.entries(model.tier_beta).sort();
  draw("c-elast", {
    type: "bar",
    data: { labels: tiers.map(([t]) => tierName(t)), datasets: [{ label: "Elasticity", data: tiers.map(([, b]) => b), backgroundColor: accent, borderRadius: 2 }] },
    options: { plugins: { legend: { display: false } } },
  });
  table("t-model", [
    { key: "term", label: "Term", f: (v) => termLabel(v) },
    { key: "coef", label: "Coef", num: true, f: (v) => fmt(v, 3) },
    { key: "t", label: "t-stat", num: true, f: (v) => fmt(v, 1) },
    { key: "ci_low", label: "95% CI", num: true, f: (_, r) => `${fmt(r.ci_low, 3)} to ${fmt(r.ci_high, 3)}` },
  ], model.terms);

  const roiLabel = (r) => (r.channel === "calls" ? `${channelLabel("calls")} (${tierName(r.scope)})` : channelLabel(r.channel));
  draw("c-roi", {
    type: "bar",
    data: { labels: roi.map(roiLabel), datasets: [{ label: "ROI (x)", data: roi.map((r) => r.roi), backgroundColor: roi.map((r) => (r.roi >= 1 ? accent : cssVar("--bad"))), borderRadius: 2 }] },
    options: { indexAxis: "y", plugins: { legend: { display: false } } },
  });
  table("t-roi", [
    { key: "channel", label: "Channel", f: (v) => channelLabel(v) },
    { key: "scope", label: state.profile.labels.tier, f: (v, r) => (r.channel === "calls" ? tierName(v) : "All") },
    { key: "incr_trx_per_unit", label: T("{metric} / unit"), num: true, f: (v) => fmt(v, 3) },
    { key: "cost_per_unit", label: "Cost", num: true, f: money },
    { key: "roi", label: "ROI", num: true, f: (v) => `${fmt(v, 2)}x` },
  ], roi);

  const decays = Object.entries(model.decay_scores).map(([d, r2]) => ({ decay: Number(d), r2, best: Number(d) === model.decay }));
  table("t-decay", [
    { key: "decay", label: "Monthly decay", f: (v) => `${fmt(v * 100)}%` },
    { key: "r2", label: `Within-${state.profile.labels.entity} R²`, num: true, f: (v) => fmt(v, 4) },
    { key: "best", label: "Selected", f: (v) => (v ? "✓ best fit" : "") },
  ], decays);
}
