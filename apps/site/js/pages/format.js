/** Plain-language formatting shared by every page.
 *  Internal identifiers (release:…, object:…, sha256:…) never appear in primary
 *  UI text; they belong in a provenance block built by `provenanceBlock`. */
import { node } from './render.js';

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const MONTHS_SHORT = MONTHS.map((m) => m.slice(0, 3));

/** Public reference data for the stations in the release (NOAA GHCN-Daily ids).
 *  The first thirteen are the listed CME U.S. temperature locations; the five
 *  Nebraska airports are research proxies only. */
export const STATIONS = {
  USW00013874: { city: 'Atlanta', state: 'GA', name: 'Hartsfield-Jackson International', code: 'A', role: 'listed' },
  USW00014739: { city: 'Boston', state: 'MA', name: 'Logan International', code: 'B', role: 'listed' },
  USW00023152: { city: 'Burbank', state: 'CA', name: 'Burbank-Glendale-Pasadena', code: 'C', role: 'listed' },
  USW00094846: { city: 'Chicago', state: 'IL', name: "O'Hare International", code: 'D', role: 'listed' },
  USW00093814: { city: 'Cincinnati', state: 'OH', name: 'Cincinnati/Northern Kentucky International', code: 'E', role: 'listed' },
  USW00003927: { city: 'Dallas-Fort Worth', state: 'TX', name: 'Dallas-Fort Worth International', code: 'F', role: 'listed' },
  USW00012960: { city: 'Houston', state: 'TX', name: 'George Bush Intercontinental', code: 'G', role: 'listed' },
  USW00023169: { city: 'Las Vegas', state: 'NV', name: 'McCarran International', code: 'H', role: 'listed' },
  USW00014922: { city: 'Minneapolis', state: 'MN', name: 'Minneapolis-St. Paul International', code: 'I', role: 'listed' },
  USW00014732: { city: 'New York', state: 'NY', name: 'LaGuardia', code: 'J', role: 'listed' },
  USW00013739: { city: 'Philadelphia', state: 'PA', name: 'Philadelphia International', code: 'K', role: 'listed' },
  USW00024229: { city: 'Portland', state: 'OR', name: 'Portland International', code: 'L', role: 'listed' },
  USW00023232: { city: 'Sacramento', state: 'CA', name: 'Sacramento Executive', code: 'M', role: 'listed' },
  USW00014942: { city: 'Omaha', state: 'NE', name: 'Eppley Airfield', code: 'N', role: 'research' },
  USW00014939: { city: 'Lincoln', state: 'NE', name: 'Lincoln Airport', code: 'O', role: 'research' },
  USW00014935: { city: 'Grand Island', state: 'NE', name: 'Central Nebraska Regional', code: 'P', role: 'research' },
  USW00024023: { city: 'North Platte', state: 'NE', name: 'North Platte Regional', code: 'Q', role: 'research' },
  USW00024028: { city: 'Scottsbluff', state: 'NE', name: 'Heilig Field', code: 'R', role: 'research' },
};
const STATION_BY_NAME = Object.fromEntries(Object.entries(STATIONS).map(([id, s]) => [s.name, { id, ...s }]));

/** Stable station colours (index order of STATIONS). */
export const STATION_COLORS = ['#1f6f80', '#c2543a', '#5b7d3f', '#d08c2a', '#7b5aa6', '#2f8fa0', '#a3543f', '#3d6b8f', '#8a7a2a', '#b5476d', '#4f8f6a', '#6e6e9e', '#9a6b3a', '#3a8f8f', '#a04f9a', '#5e7f9a', '#8f5e3a', '#4a9a5e'];
export function stationColor(idOrName) {
  const id = stationId(idOrName); const ids = Object.keys(STATIONS); const index = ids.indexOf(id);
  return index >= 0 ? STATION_COLORS[index] : '#9aa7a4';
}

export function stationId(value) {
  if (!value) return null; const raw = String(value).split(':')[0];
  if (STATIONS[raw]) return raw;
  return STATION_BY_NAME[String(value)]?.id || null;
}
/** "Dallas-Fort Worth (DFW International)" style label; falls back to the raw name. */
export function stationLabel(value, { withName = true } = {}) {
  const id = stationId(value); const station = id ? STATIONS[id] : null;
  if (!station) return value == null ? 'Unavailable' : String(value).split(':')[0];
  return withName ? `${station.city}, ${station.state} · ${station.name}` : `${station.city}, ${station.state}`;
}
export function stationCity(value) { const id = stationId(value); return id ? STATIONS[id].city : (value == null ? 'Unavailable' : String(value)); }

/** Index pair helpers: "HDD-01" → "January heating degree days". */
export function pairParts(pairId) { const match = /^(HDD|CDD)-(\d{2})$/.exec(String(pairId || '')); if (!match) return null; return { kind: match[1], month: Number(match[2]) }; }
export function pairLabel(pairId, { short = false } = {}) {
  const parts = pairParts(pairId); if (!parts) return String(pairId || 'Unavailable');
  const month = short ? MONTHS_SHORT[parts.month - 1] : MONTHS[parts.month - 1];
  const kind = parts.kind === 'HDD' ? (short ? 'HDD' : 'heating degree days') : (short ? 'CDD' : 'cooling degree days');
  return short ? `${month} ${kind}` : `${month} ${kind}`;
}
export function pairKindLabel(pairId) { const parts = pairParts(pairId); return parts ? (parts.kind === 'HDD' ? 'Heating degree days (HDD)' : 'Cooling degree days (CDD)') : 'Index'; }
export function monthName(pairId) { const parts = pairParts(pairId); return parts ? MONTHS[parts.month - 1] : ''; }

/** Numbers. Every formatter returns "Unavailable" for null/NaN rather than "0". */
const finite = (value) => value !== null && value !== '' && value !== undefined && Number.isFinite(Number(value));
export const NA = 'Unavailable';
export function pct(value, digits = 1) { return finite(value) ? `${(Number(value) * 100).toFixed(digits)}%`.replace(/^-/, '−') : NA; }
export function pts(value, digits = 1) { if (!finite(value)) return NA; const v = Number(value) * 100; const sign = v > 0 ? '+' : v < 0 ? '−' : ''; return `${sign}${Math.abs(v).toFixed(digits)} pts`; }
export function num(value, digits = 0) { return finite(value) ? Number(value).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }).replace(/^-/, '−') : NA; }
export function signed(value, digits = 0) { if (!finite(value)) return NA; const v = Number(value); return `${v > 0 ? '+' : v < 0 ? '−' : ''}${num(Math.abs(v), digits)}`; }
export function usd(value, digits = 0) { if (!finite(value)) return NA; const v = Number(value); return `${v < 0 ? '−' : ''}$${num(Math.abs(v), digits)}`; }
/** Ranges always read "low to high" so a negative end is unambiguous. */
export function rangeText(low, high, format = num) { if (!finite(low) && !finite(high)) return NA; return `${format(low)} to ${format(high)}`; }
export function km(value) { return finite(value) ? `${num(Math.round(Number(value)))} km` : NA; }
export function degreeDays(value, digits = 0) { return finite(value) ? `${num(value, digits)} degree days` : NA; }
export function ratio(value, digits = 2) { if (!finite(value)) return NA; const rounded = Number(Number(value).toFixed(digits)) === 0 ? 0 : Number(value); return rounded.toFixed(digits).replace(/^-/, '−'); }

/** Dates: "2026-07-01" → "1 Jul 2026". Accepts ISO date or datetime strings. */
export function dateShort(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value || '')); if (!match) return value ? String(value) : NA;
  return `${Number(match[3])} ${MONTHS_SHORT[Number(match[2]) - 1]} ${match[1]}`;
}
export function dateRange(start, end) { if (!start && !end) return NA; return `${dateShort(start)} – ${dateShort(end)}`; }
export function seasonRange(seasons) { const list = (Array.isArray(seasons) ? seasons : []).map(Number).filter(Number.isFinite).sort((a, b) => a - b); if (!list.length) return NA; const contiguous = list.at(-1) - list[0] + 1 === list.length; return contiguous ? `${list[0]}–${list.at(-1)}` : `${list[0]}–${list.at(-1)} (${list.length} seasons, with gaps)`; }

/** Identifiers: "release:306bdf…" → "306bdf8f". Use only inside provenance. */
export function shortId(value, length = 8) { if (!value) return NA; const text = String(value); const hex = /([a-f0-9]{16,})/i.exec(text); return hex ? hex[1].slice(0, length) : text.slice(0, length); }
export function releaseLabel(releaseId) { return releaseId ? `Release ${shortId(releaseId)}` : 'Release unavailable'; }

/** Machine status codes → sentences. Unknown codes fall back to a readable form. */
const STATUS_TEXT = {
  eligible_modeled_proxy: 'A listed station is available to hedge this county in the coming contract window.',
  unavailable_aligned_station_model: 'No listed station could be modelled for this county and month, so there is no station to hedge it with this season.',
  evaluable: 'Historical hedge evidence was evaluated on matched seasons.',
  selected: 'A station was selected at the decision date.',
  ok: 'Complete evidence.',
  available: 'Available',
  unavailable: 'Unavailable',
  partial: 'Partial evidence',
  missing_model_load_assumption: 'No risk-transfer loading is assumed in this release.',
  no_market_observation: 'No market price is observed; nothing here is a quote.',
  not_final_national_or_predictive_validation: 'A bounded study, not the national validation.',
  bounded_or_retrospective_evidence: 'Retrospective, bounded evidence.',
  two_scoreable_origins_inconclusive: 'Only two scoreable origins, so the comparison is inconclusive.',
  degenerate_target: 'The index barely varies in this county and month, so effectiveness is undefined.',
};
export function statusText(value) {
  if (value == null) return NA;
  if (typeof value === 'object') { const code = value.reason_code && value.reason_code !== 'ok' && value.reason_code !== 'selected' ? value.reason_code : value.status; return statusText(code); }
  const key = String(value); return STATUS_TEXT[key] || humanize(key);
}
export function humanize(value) { if (value == null) return NA; return String(value).replace(/^[a-z_]+:/, '').replaceAll('_', ' ').replace(/^\w/, (c) => c.toUpperCase()); }

/** Layer names as shown on the map controls. Falls back to the payload label. */
const LAYER_TEXT = {
  matched_he: { name: 'Hedge effectiveness', help: 'Share of a county\'s year-to-year variation in this index that hedging with the selected listed station would have removed, over matched past seasons. Higher is better.', kind: 'sequential', format: pct },
  delta_he: { name: 'Gain vs nearest station', help: 'Hedge effectiveness of the selected station minus the nearest listed station, in percentage points. Teal means the selection rule helped; rust means the nearest station would have done better.', kind: 'diverging', format: pts },
  current_proxy: { name: 'Selected station', help: 'The listed station chosen for the current contract window using only information available at the decision date.', kind: 'category', format: (v) => stationCity(v) },
  residual_risk: { name: 'Residual risk', help: 'Root-mean-square error of the hedged county index, in degree days. Larger means more basis risk remains after hedging.', kind: 'sequential-bad', format: (v) => num(v) },
  selection_stability: { name: 'Selection stability', help: 'How often the same station was chosen across historical decision points. 100% means the choice never changed.', kind: 'sequential', format: pct },
  interval_width: { name: 'Uncertainty', help: 'Width of the 95% interval around the gain versus the nearest station, in percentage points. Wider means the historical evidence is noisier.', kind: 'sequential-bad', format: pts },
  coverage: { name: 'Seasons evaluated', help: 'Number of matched historical seasons behind the county\'s evaluation.', kind: 'sequential', format: (v) => num(v) },
  current_availability: { name: 'Availability', help: 'Whether a listed station is available to hedge this county in the coming contract window.', kind: 'category', format: (v) => (v === 'eligible_modeled_proxy' ? 'Station available' : v == null ? NA : 'No station') },
};
export function layerMeta(key, sample) { const meta = LAYER_TEXT[key]; return { key, name: meta?.name || sample?.label || humanize(key), help: meta?.help || sample?.label || '', units: sample?.units || '', kind: meta?.kind || (sample?.units === 'category' ? 'category' : 'sequential'), format: meta?.format || ((v) => (finite(v) ? num(v, 2) : v == null ? NA : String(v))) }; }
export const LAYER_ORDER = ['matched_he', 'delta_he', 'current_proxy', 'residual_risk', 'selection_stability', 'interval_width', 'coverage', 'current_availability'];

/** Provenance block: everything a reproducer needs, out of the main flow. */
export function provenanceBlock(entries, { summary = 'Provenance and identifiers' } = {}) {
  const details = node('details', undefined, { class: 'provenance' }); details.append(node('summary', summary));
  const table = node('table', undefined, { class: 'kv' }); const body = node('tbody');
  entries.filter(([, value]) => value !== undefined && value !== null && value !== '').forEach(([label, value]) => {
    const row = node('tr'); row.append(node('th', label, { scope: 'row' })); const cell = node('td'); const text = Array.isArray(value) ? value.join(', ') : String(value); cell.append(node('code', text)); row.append(cell); body.append(row);
  });
  table.append(body); details.append(table); return details;
}
export function envelopeProvenance(record, extra = []) {
  if (!record) return provenanceBlock(extra);
  return provenanceBlock([
    ['Release', record.release_id], ['Result object', record.object_id], ['Analysis', record.analysis_id], ['Data vintage', record.data_vintage_id], ['Models', record.model_spec_ids], ['Scenario set', record.scenario_set_id], ['Valuation date', record.valuation_asof], ['Evidence', record.evidence_reference], ['Sources', (record.source_artifact_ids || []).slice(0, 6).concat((record.source_artifact_ids || []).length > 6 ? [`… ${record.source_artifact_ids.length - 6} more`] : [])], ...extra,
  ]);
}

/** Small helpers for building UI. */
export function tile(label, value, sub, { small = false, na = false } = {}) {
  const box = node('div', undefined, { class: 'tile' }); box.append(node('span', label, { class: 'label' }));
  const v = node('span', value, { class: `value${small ? ' small' : ''}${na || value === NA ? ' na' : ''}` }); box.append(v);
  if (sub) box.append(node('span', sub, { class: 'sub' })); return box;
}
export function tiles(list) { const grid = node('div', undefined, { class: 'tiles' }); list.forEach((t) => grid.append(t)); return grid; }
export function kvTable(entries) {
  const table = node('table', undefined, { class: 'kv' }); const body = node('tbody');
  entries.forEach(([label, value]) => { const row = node('tr'); row.append(node('th', label, { scope: 'row' })); const cell = node('td'); if (value instanceof Node) cell.append(value); else cell.textContent = value == null || value === '' ? NA : String(value); row.append(cell); body.append(row); });
  table.append(body); return table;
}
export function dataTable(headers, rows, { numeric = [] } = {}) {
  const wrap = node('div', undefined, { class: 'table-wrap' }); const table = node('table', undefined, { class: 'metric-table' }); const head = node('thead'); const line = node('tr');
  headers.forEach((label, index) => line.append(node('th', label, numeric.includes(index) ? { class: 'num' } : {}))); head.append(line);
  const body = node('tbody'); rows.forEach((values) => { const row = node('tr'); if (values.__class) row.className = values.__class; values.forEach((value, index) => { const cell = node('td', undefined, numeric.includes(index) ? { class: 'num' } : {}); if (value instanceof Node) cell.append(value); else cell.textContent = value == null || value === '' ? NA : String(value); row.append(cell); }); body.append(row); });
  table.append(head, body); wrap.append(table); return wrap;
}
export function countyLabel(county, fips) { if (!county?.name) return fips || NA; return `${county.name}, ${county.state || ''}`.replace(/, $/, ''); }
export function button(label, { primary = false, quiet = false, small = false, type = 'button', ...attrs } = {}) { return node('button', label, { type, class: `btn${primary ? ' btn-primary' : ''}${quiet ? ' btn-quiet' : ''}${small ? ' btn-small' : ''}`, ...attrs }); }
export function linkButton(label, href, { primary = false, quiet = false } = {}) { return node('a', label, { href, class: `btn${primary ? ' btn-primary' : ''}${quiet ? ' btn-quiet' : ''}` }); }
export function field(labelText, control, hint) { const label = node('label', undefined, { class: 'field' }); label.append(document.createTextNode(labelText)); if (hint) label.append(node('span', hint, { class: 'hint' })); label.append(control); return label; }
