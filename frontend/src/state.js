// Shared state and the label system: every heading is a template ("{metric} per {unit}") filled from the loaded data set.
export const FILTER_IDS = { region: "f-region", specialty: "f-specialty", tier: "f-tier", start: "f-start", end: "f-end" };

export const state = {
  meta: null,
  profile: null,
  page: "overview",
  budget: 0,
  hcp: { q: "", sort: "trx", order: "desc", page: 1, size: 15 },
};

export function pluralize(word) {
  const s = String(word);
  if (/[^aeiou]y$/i.test(s)) return `${s.slice(0, -1)}ies`;
  if (/(s|x|ch|sh)$/i.test(s)) return s;
  return `${s}s`;
}

let tokenCache = {};

export function setProfile(profile) {
  state.profile = profile;
  const lb = profile.labels;
  const ch = Object.fromEntries(profile.channels.map((c) => [c.key, c]));
  const base = {
    metric: lb.metric, entity: lb.entity, entities: lb.entities,
    primary: ch.calls.label, unit: ch.calls.unit, second: ch.samples.label, third: ch.emails.label,
    region: lb.region, specialty: lb.specialty, tier: lb.tier, territory: lb.territory,
    territories: pluralize(lb.territory), rep: lb.rep,
  };
  tokenCache = { ...base };
  for (const [k, v] of Object.entries(base)) tokenCache[`${k}_l`] = String(v).toLowerCase();
}

/** Fill {tokens} in a template string. Unknown tokens are left as they are. */
export const T = (template) => String(template).replace(/\{(\w+)\}/g, (m, k) => (k in tokenCache ? tokenCache[k] : m));

/** Re-label static markup: data-t (text), data-t-placeholder, data-t-title. */
export function applyLabels(root = document) {
  root.querySelectorAll("[data-t]").forEach((el) => { el.textContent = T(el.dataset.t); });
  root.querySelectorAll("[data-t-placeholder]").forEach((el) => { el.placeholder = T(el.dataset.tPlaceholder); });
  root.querySelectorAll("[data-t-title]").forEach((el) => { el.title = T(el.dataset.tTitle); });
}

export const dimensions = () => state.profile.dimensions;
export const activeDimensions = () => state.profile.dimensions.filter((d) => d.active);
export const dimLabel = (key) => state.profile.dimensions.find((d) => d.key === key)?.label ?? key;
export const channelLabel = (key) => state.profile.channels.find((c) => c.key === key)?.label ?? key;
export const channelActive = (key) => state.profile.channels.some((c) => c.key === key && c.active);

/** "A" -> "Tier A" (short codes get the tier label); descriptive values such as "Platinum" stay as they are. */
export const tierName = (value) => (String(value).length <= 2 ? `${state.profile.labels.tier} ${value}` : String(value));

/** Human wording of a regression term key from the API (calls_tier_A, samples, emails). */
export function termLabel(term) {
  if (term.startsWith("calls_tier_")) return `${channelLabel("calls")} · ${tierName(term.slice("calls_tier_".length))}`;
  return channelLabel(term);
}
