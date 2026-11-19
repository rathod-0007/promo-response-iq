import { getJSON } from "../api.js";
import { activeDimensions, tierName } from "../state.js";
import { filterParams } from "../ui.js";

/** GET an API path with the current filters (plus any extra parameters). */
export const api = (path, extra = {}) => getJSON(path, { ...filterParams(), ...extra });

/** Table columns for the dimensions that exist in the loaded data (e.g. specialty, region, tier), in a fixed order. */
export function dimensionColumns(order = ["specialty", "region", "tier"]) {
  const active = Object.fromEntries(activeDimensions().map((d) => [d.key, d]));
  return order.filter((k) => active[k]).map((k) => ({
    key: k, label: active[k].label, f: k === "tier" ? (v) => tierName(v) : undefined,
  }));
}

/** An error the router shows as a notice (not enough data, feature unavailable...). */
export function notice(message) {
  const e = new Error(message);
  e.status = 422;
  return e;
}
