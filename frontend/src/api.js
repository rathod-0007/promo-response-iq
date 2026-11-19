// Thin API client. VITE_API_BASE is empty in development (Vite proxies /api) and when the API serves the built UI.
export const API = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message, status, issues = []) {
    super(message);
    this.status = status;
    this.issues = issues;
  }
}

async function check(res) {
  if (res.ok) return res;
  let detail = res.statusText;
  try { detail = (await res.json()).detail ?? detail; } catch (_) { /* not JSON */ }
  if (typeof detail === "string") throw new ApiError(detail, res.status);
  if (Array.isArray(detail)) throw new ApiError(detail.map((d) => d.msg).join("; "), res.status);
  throw new ApiError(detail.message || "Request failed", res.status, detail.issues || []);
}

export function url(path, params = {}) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, v);
  const qs = p.toString();
  return `${API}${path}${qs ? `?${qs}` : ""}`;
}

export async function getJSON(path, params) { return (await check(await fetch(url(path, params)))).json(); }
export async function postJSON(path, body) {
  const res = await fetch(url(path), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
  return (await check(res)).json();
}
export async function postFile(path, file) {
  const form = new FormData();
  form.append("file", file);
  return (await check(await fetch(url(path), { method: "POST", body: form }))).json();
}
