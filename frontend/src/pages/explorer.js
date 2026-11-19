import { $, fmt, table } from "../ui.js";
import { T, state } from "../state.js";
import { api, dimensionColumns } from "./common.js";

let reload = () => {};
export function bindExplorer(onChange) { reload = onChange; }

export async function load() {
  const h = state.hcp;
  const res = await api("/api/hcps", { q: h.q, sort: h.sort, order: h.order, page: h.page, page_size: h.size });
  const pages = Math.max(1, Math.ceil(res.total / res.page_size));
  if (h.page > pages) { h.page = pages; return load(); }
  const from = res.total ? (res.page - 1) * res.page_size + 1 : 0;
  const to = Math.min(res.total, res.page * res.page_size);
  $("hcp-count").textContent = `${fmt(res.total)} ${T("{entities}")}`;
  $("pg-info").textContent = res.total ? `${fmt(from)}–${fmt(to)} of ${fmt(res.total)}` : "No results";
  $("pg-prev").disabled = res.page <= 1;
  $("pg-next").disabled = res.page >= pages;
  const onSort = (key) => { h.order = h.sort === key && h.order === "desc" ? "asc" : "desc"; h.sort = key; h.page = 1; reload(); };
  table("t-hcps", [
    { key: "name", label: T("{entity}"), sort: true },
    ...dimensionColumns().map((c) => ({ ...c, sort: true })),
    { key: "trx", label: T("{metric}"), num: true, sort: true, f: (v) => fmt(v) },
    { key: "calls", label: T("{primary}"), num: true, sort: true, f: (v) => fmt(v) },
    { key: "trx_per_call", label: T("{metric} / {unit}"), num: true, sort: true, f: (v) => fmt(v, 2) },
  ], res.rows, { sort: { key: h.sort, order: h.order }, onSort, empty: T("No {entities} match your search") });
}
