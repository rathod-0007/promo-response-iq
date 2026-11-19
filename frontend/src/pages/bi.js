// BI & integrations: connection details, published objects, refresh/CSV pack, and per-tool connection steps.
import { getJSON, postJSON, url } from "../api.js";
import { $, el, fmt, showNotice } from "../ui.js";

let hooks = { toast: () => {} };
export function bindBi(h) { hooks = { ...hooks, ...h }; }

function copyButton(text) {
  const b = el("button", { class: "copy", type: "button", text: "Copy", "aria-label": `Copy ${text}` });
  b.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(text); b.textContent = "Copied"; } catch (_) { b.textContent = "Select and copy"; }
    setTimeout(() => { b.textContent = "Copy"; }, 1400);
  });
  return b;
}

function renderConnection(c) {
  const rows = [["Database type", "PostgreSQL"], ["Host", c.host || "localhost"], ["Port", String(c.port)], ["Database", c.database],
    ["Schema", c.schema], ["User", c.user || "(your database user)"]];
  const dl = $("bi-conn");
  dl.innerHTML = "";
  rows.forEach(([k, v]) => dl.append(el("dt", { text: k }), el("dd", {}, el("code", { text: v }), copyButton(v))));
}

function renderObjects(info) {
  const root = $("bi-objects");
  root.innerHTML = "";
  info.objects.forEach((o) => {
    const sum = el("summary", {}, el("strong", { text: o.name }), el("span", { class: "tag", text: o.kind }),
      el("span", { class: "hint", text: `${fmt(o.rows)} rows` }), el("span", { class: "hint grow", text: o.description }));
    const cols = el("p", { class: "cols", text: o.columns.map((c) => `${c.name} (${c.type})`).join(" · ") });
    root.appendChild(el("details", {}, sum, cols));
  });
  $("bi-refreshed").textContent = info.refreshed_at ? `Analysis tables published ${new Date(info.refreshed_at).toLocaleString()}` : "Analysis tables not published yet";
  const notes = $("bi-notes");
  notes.innerHTML = "";
  info.notes.forEach((n) => notes.appendChild(el("li", { text: n })));
  notes.hidden = !info.notes.length;
}

function renderGuides(c) {
  const where = `${c.host || "localhost"}:${c.port}`;
  const guides = [
    { tool: "Tableau", steps: [
      `Fastest: download the Tableau workbook above and open the .twbx in Tableau Public (free) or Desktop.`,
      `Or build your own: Connect → To a Server → PostgreSQL.`, `Server ${c.host || "localhost"}, port ${c.port}, database ${c.database}; sign in with a read-only user.`,
      `Pick schema ${c.schema}. Drag bi_fact_hcp_month onto the canvas, then relate bi_dim_hcp (hcp_id), bi_dim_month (month_start) and bi_dim_territory (territory_id).`,
      `No database access? Connect → To a File → Text file, and use the CSV pack.`] },
    { tool: "Power BI", steps: [
      `Fastest: download the Power BI project above, unzip it, open PromoResponseIQ.pbip in Power BI Desktop (free), then Home → Refresh.`,
      `Or build your own: Home → Get data → PostgreSQL database.`, `Server ${where}, database ${c.database}. Choose Import (or DirectQuery for live data).`,
      `Select the bi_* tables and views. In Model view relate hcp_id, month_start and territory_id (one dimension to many facts).`,
      `Offline? Get data → Text/CSV, or Get data → Web with the API (http://localhost:8000/api/kpis returns JSON).`] },
    { tool: "Sisense", steps: [
      `Data → New model → Add data → PostgreSQL connector.`, `Host ${c.host || "localhost"}, port ${c.port}, database ${c.database}, schema ${c.schema}.`,
      `Add bi_fact_hcp_month and the bi_dim_* tables, then define relationships on hcp_id, month_start and territory_id.`,
      `Or upload the CSV pack files as CSV data sources.`] },
  ];
  const root = $("bi-guides");
  root.innerHTML = "";
  guides.forEach((g) => root.appendChild(el("article", { class: "card guide" }, el("h2", { text: g.tool }), el("ol", {}, g.steps.map((s) => el("li", { text: s }))))));
}

export function bindBiControls() {
  $("bi-refresh").addEventListener("click", async () => {
    const b = $("bi-refresh");
    b.disabled = true;
    b.textContent = "Publishing...";
    try { await postJSON("/api/bi/refresh"); await load(); } catch (e) { showNotice(e.message); }
    b.disabled = false;
    b.textContent = "Refresh analysis tables";
  });
  $("bi-csv").href = url("/api/export/bi");
  $("bi-tableau").href = url("/api/export/tableau");
  $("bi-powerbi").href = url("/api/export/powerbi");
}

export async function load() {
  const info = await getJSON("/api/bi/info");
  renderConnection(info.connection);
  renderObjects(info);
  renderGuides(info.connection);
}
