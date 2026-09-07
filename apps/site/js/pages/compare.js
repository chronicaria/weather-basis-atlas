/** Compare page: two to six counties side by side on one index.
 *  Data contract, exports and the joint-weather arithmetic are unchanged from V2;
 *  this module only changes how they are chosen, read and presented. */
import { node, replacePanel } from './render.js';
import { findCountyMatches } from '../state/selection.js';
import {
  NA, button, countyLabel, dataTable, dateShort, field, km, linkButton, num, pairLabel, pairParts, pct, provenanceBlock, pts, rangeText, ratio, seasonRange, signed, stationCity, statusText,
} from './format.js';

const MAX_COUNTIES = 6;
const MIN_COUNTIES = 2;
const MAX_MATCHES = 12;
const finite = (value) => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
const WORDS = ['none', 'one', 'two', 'three', 'four', 'five', 'six'];
const count = (n) => WORDS[n] || num(n);

/* ---------- export: file content is identical to V2 ---------- */
function download(records, fips, indexId) {
  const body = { schema_version: '2.0', comparison_fips: fips, index_id: indexId, release_id: records[0]?.release_id, records };
  const blob = new Blob([JSON.stringify(body, null, 2)], { type: 'application/json' });
  const link = node('a', 'Download comparison (JSON)', { href: URL.createObjectURL(blob), download: `weather-basis-compare-${indexId}.json`, class: 'btn' });
  link.addEventListener('click', () => setTimeout(() => URL.revokeObjectURL(link.href), 1000));
  return link;
}

/* ---------- joint weather: same checks and arithmetic as V2, raw numbers returned ---------- */
async function jointWeather(fips, indexId, loadObject) {
  const loaded = await Promise.all(fips.map((id) => loadObject(`county_scenarios:${id}`).catch(() => null)));
  const usable = loaded.map((record, index) => ({ record, fips: fips[index] })).filter(({ record }) => record?.payload?.matrix);
  if (usable.length < 2) return null;
  const first = usable[0].record.payload.matrix;
  const shared = usable.every(({ record }) => record.payload.matrix.parent_scenario_set_id === first.parent_scenario_set_id
    && JSON.stringify(record.payload.matrix.scenario_ids) === JSON.stringify(first.scenario_ids));
  if (!shared) return { error: 'These counties’ weather scenarios were not drawn from one shared set, so no joint summary is shown.' };
  const values = usable.map(({ record, fips: id }) => {
    const matrix = record.payload.matrix; const column = matrix.entity_ids.indexOf(`${id}:${indexId}`);
    return column < 0 ? null : matrix.values.map((row) => row[column]);
  });
  if (values.some((value) => !value)) return { error: `At least one of these counties has no simulated ${pairLabel(indexId)} outcomes, so no joint summary is shown.` };
  const mean = (x) => x.reduce((a, b) => a + b, 0) / x.length;
  const sd = (x) => Math.sqrt(x.reduce((a, b) => a + (b - mean(x)) ** 2, 0) / Math.max(1, x.length - 1));
  const corr = (a, b) => { const ma = mean(a); const mb = mean(b); return a.reduce((s, x, i) => s + (x - ma) * (b[i] - mb), 0) / Math.sqrt(a.reduce((s, x) => s + (x - ma) ** 2, 0) * b.reduce((s, x) => s + (x - mb) ** 2, 0)); };
  return {
    ids: usable.map(({ fips: id }) => id),
    records: usable.map(({ record }) => record),
    count: first.scenario_ids.length,
    setId: first.parent_scenario_set_id,
    stats: values.map((column) => ({ mean: mean(column), sd: sd(column) })),
    correlation: values.map((a) => values.map((b) => corr(a, b))),
  };
}

/* ---------- one county record → the facts the table and the reading need ---------- */
function describeRecord(record, fips, county) {
  const payload = record?.payload;
  if (!payload) return { fips, county, record, evaluable: false, loadError: record?.reason_code || NA, reason: 'This county’s record could not be loaded for this index.' };
  const matched = payload.matched_policy || {}; const asof = payload.selection_asof || {}; const availability = payload.current_availability || {}; const historical = payload.historical_evidence || {};
  const alternatives = Array.isArray(payload.alternatives) ? payload.alternatives : [];
  const stationId = asof.station_id || asof.station_name || null;
  const selectedMeta = alternatives.find((item) => item.station_id === asof.station_id || item.station_name === asof.station_name);
  const nearest = [...alternatives].sort((a, b) => (a.distance_km ?? Infinity) - (b.distance_km ?? Infinity))[0] || null;
  const nearestId = nearest ? (nearest.station_id || nearest.station_name) : null;
  const he = finite(matched.metric?.value) ? Number(matched.metric.value) : null;
  const evaluable = historical.status === 'evaluable' && he !== null;
  const noCurrentStation = Boolean(availability.status) && availability.status !== 'eligible_modeled_proxy';
  return {
    fips, county, record, evaluable, he,
    nearestHe: finite(matched.nearest_he) ? Number(matched.nearest_he) : null,
    delta: finite(matched.delta_he) ? Number(matched.delta_he) : null,
    low: finite(matched.interval?.low) ? Number(matched.interval.low) : null,
    high: finite(matched.interval?.high) ? Number(matched.interval.high) : null,
    residual: finite(matched.residual_rmse_degree_days) ? Number(matched.residual_rmse_degree_days) : null,
    seasons: finite(matched.n_common) ? Number(matched.n_common) : null,
    seasonList: Array.isArray(matched.common_seasons) ? matched.common_seasons : [],
    stationId, distance: selectedMeta?.distance_km, nearestId,
    nearestIsSelected: Boolean(nearest && stationId && (nearest.station_id === asof.station_id || nearest.station_name === asof.station_name)),
    identicalToNearest: finite(matched.delta_he) && Number(matched.delta_he) === 0 && finite(matched.interval?.low) && Number(matched.interval.low) === 0 && finite(matched.interval?.high) && Number(matched.interval.high) === 0,
    decisionDate: asof.decision_time || asof.valuation_date || null,
    reason: evaluable ? null : statusText(matched.reason_code && matched.reason_code !== 'ok' ? matched.reason_code : historical),
    stationNote: noCurrentStation ? statusText(availability.status) : null,
    metricDefinition: matched.metric?.definition, intervalMethod: matched.interval?.method,
  };
}

/* ---------- the side-by-side table ---------- */
/** Hedge effectiveness sits in the second column so it is visible on a phone before the table is scrolled. */
const HEADERS = ['County', 'Hedge effectiveness', 'Selected station', 'Nearest station (its effectiveness)', 'Gain vs nearest', '95% band on gain', 'Residual risk (degree days)', 'Seasons'];
const NUMERIC_COLUMNS = [3, 4, 5, 6, 7];
const BAND_COLUMN = 5;

/** A hint shown only while its table really is wider than the page; compare.js checks after layout and on resize. */
function scrollHint(text) { const hint = node('p', text, { class: 'status scroll-hint' }); hint.hidden = true; return hint; }
function syncScrollHints(root) {
  root.querySelectorAll('.scroll-hint + .table-wrap').forEach((wrap) => { wrap.previousElementSibling.hidden = !(wrap.scrollWidth > wrap.clientWidth + 1); });
}

/** One table row. Season identities are never listed per row: the count is shown, and
 *  the year span (via seasonRange) only when the counties were not scored on the same seasons. */
function tableRow(item, { showRange = false } = {}) {
  const name = countyLabel(item.county, item.fips);
  if (!item.evaluable) { const row = [name, item.reason]; row.__class = 'is-muted'; row.__span = true; return row; }
  const station = node('span');
  if (item.stationId) {
    station.append(document.createTextNode(stationCity(item.stationId)));
    if (finite(item.distance)) station.append(node('span', ` · ${km(item.distance)}`, { class: 'muted small nowrap' }));
  } else station.append(node('span', 'None for the coming season', { class: 'muted' }));
  const heCell = node('span', undefined, { class: 'nowrap' });
  heCell.append(node('span', undefined, { class: `bar${item.he < 0 ? ' neg' : ''}`, style: `width:${Math.min(100, Math.abs(item.he) * 60)}px` }), document.createTextNode(pct(item.he)));
  // Station first, then its score, so the percentages still line up on the right edge of a numeric column.
  const nearestCell = node('span');
  if (item.nearestId) nearestCell.append(node('span', `${stationCity(item.nearestId)} · `, { class: 'muted small' }));
  nearestCell.append(document.createTextNode(pct(item.nearestHe)));
  let band = NA;
  if (item.identicalToNearest) band = node('span', 'no difference', { class: 'muted' });
  // rangeText reads "low to high", so a negative end of the band is never mistaken for a dash.
  // The non-breaking spaces leave one wrap point, before the upper end, so "pts" never lands alone.
  else if (item.low != null && item.high != null) band = `${rangeText(item.low * 100, item.high * 100, (value) => signed(value, 1))}\u00A0pts`.replace(' to ', '\u00A0to ');
  const seasonsCell = node('span');
  seasonsCell.append(document.createTextNode(num(item.seasons)));
  if (showRange && item.seasonList.length) seasonsCell.append(node('span', seasonRange(item.seasonList), { class: 'muted small season-range' }));
  return [name, heCell, station, nearestCell, pts(item.delta), band, num(item.residual), seasonsCell];
}

function comparisonTable(items) {
  const ranges = new Set(items.filter((item) => item.evaluable).map((item) => seasonRange(item.seasonList)));
  const rows = items.map((item) => tableRow(item, { showRange: ranges.size > 1 }));
  const wrap = dataTable(HEADERS, rows, { numeric: NUMERIC_COLUMNS });
  wrap.classList.add('compare-table');
  wrap.querySelectorAll('tbody tr').forEach((tr, index) => {
    const cells = [...tr.children];
    if (!rows[index].__span) { cells[BAND_COLUMN].classList.add('band'); return; }
    cells.slice(2).forEach((cell) => cell.remove());
    cells[1].colSpan = HEADERS.length - 1; cells[1].classList.remove('num');
  });
  return wrap;
}

/* ---------- plain-language reading, computed from the numbers only ---------- */
function joinNames(items) {
  const names = items.map((item) => node('strong', countyLabel(item.county, item.fips)));
  const out = [];
  names.forEach((name, index) => {
    if (index > 0) out.push(index === names.length - 1 ? ' and ' : ', ');
    out.push(name);
  });
  return out;
}

function readingParagraph(items, indexId) {
  const evaluated = items.filter((item) => item.evaluable).sort((a, b) => b.he - a.he);
  const p = node('p', undefined, { class: 'sentence' });
  const push = (...parts) => parts.forEach((part) => p.append(typeof part === 'string' ? document.createTextNode(part) : part));
  const name = (item) => node('strong', countyLabel(item.county, item.fips));
  const stationOf = (item) => (item.stationId ? stationCity(item.stationId) : 'its selected station');
  const label = pairLabel(indexId);
  if (!evaluated.length) { push(`None of these counties has matched hedge evidence for ${label}; the table gives the reason for each.`); return p; }
  const best = evaluated[0]; const worst = evaluated.at(-1);
  if (evaluated.length === 1) {
    push('Only ', name(best), ` has matched evidence for ${label}: ${stationOf(best)} explains ${pct(best.he, 0)} of its year-to-year variation. The table gives the reason each other county is left out.`);
    return p;
  }
  const noisyEdge = best.delta != null && best.delta >= 0.01 && best.low != null && best.low <= 0;
  push(name(best), ` is best served: ${stationOf(best)} explains ${pct(best.he, 0)} of its ${label} variation`, noisyEdge ? ', although its edge over the nearest station is within the noise (the 95% band spans zero).' : '.');
  if (best.he - worst.he < 0.05) push(' The set is closely matched; ', name(worst), ` is lowest at ${pct(worst.he, 0)}.`);
  else if (worst.he < 0) push(' ', name(worst), ` is worst served: at ${pct(worst.he, 0)} the hedge would have added variation rather than removed it.`);
  else push(' ', name(worst), ` is worst served at ${pct(worst.he, 0)}`, worst.he < 0.5 ? ', so most of its variation would remain unhedged.' : '.');
  push(...nearestSentence(evaluated));
  const withResidual = evaluated.filter((item) => finite(item.residual));
  if (withResidual.length >= 2) {
    const lo = withResidual.reduce((a, b) => (b.residual < a.residual ? b : a)); const hi = withResidual.reduce((a, b) => (b.residual > a.residual ? b : a));
    if (lo !== hi) push(` Residual risk after hedging runs from ${num(lo.residual)} degree days (`, name(lo), `) to ${num(hi.residual)} (`, name(hi), ').');
  }
  return p;
}

/** One sentence on choosing a station by past performance versus simply taking the nearest one.
 *  It counts rather than lists, names each county once, and folds in whether the station in use
 *  for the coming season is the nearest one (in which case the gain figure comes from earlier seasons). */
function nearestSentence(evaluated) {
  const points = (value) => { const text = num(Math.abs(value) * 100, 0); return `${text} point${text === '1' ? '' : 's'}`; };
  const spread = (values) => { const lo = points(Math.min(...values)); const hi = points(Math.max(...values)); return lo === hi ? lo : `${lo.replace(/ points?$/, '')} to ${hi}`; };
  const upTo = (values) => (values.length === 1 ? points(values[0]) : `up to ${points(Math.max(...values.map(Math.abs)))}`);
  const scored = evaluated.filter((item) => item.delta != null);
  if (!scored.length) return [];
  const same = scored.filter((item) => item.identicalToNearest);
  const rest = scored.filter((item) => !item.identicalToNearest);
  const close = rest.filter((item) => Math.abs(item.delta) < 0.01);
  const worse = rest.filter((item) => item.delta <= -0.01);
  const better = rest.filter((item) => item.delta >= 0.01);
  const usingNearest = (list) => list.filter((item) => item.nearestIsSelected).length;
  const out = [];
  let explain = false;
  if (better.length === scored.length) {
    out.push(` In every county, choosing a station by past performance beat the nearest one, by ${spread(better.map((item) => item.delta))}.`);
    const current = usingNearest(better);
    if (current) { explain = true; out.push(current === better.length ? ' In each of them the station in use for the coming season is the nearest one.' : ` In ${count(current)} of them the station in use for the coming season is the nearest one.`); }
  } else {
    const groups = [
      { items: better, single: (list) => `the past-performance choice beat the nearest station, by ${upTo(list.map((item) => item.delta))}`, multi: (list) => `it beat the nearest station by ${upTo(list.map((item) => item.delta))}` },
      { items: same, single: () => 'the past-performance choice always landed on the nearest station, so there was nothing to gain or lose', multi: () => 'the two are the same station', silent: true },
      { items: close,
        single: (list) => (list.every((item) => item.delta < 0) ? `the nearest station would have done slightly better, by ${upTo(list.map((item) => item.delta))}` : 'the nearest station would have done practically as well (within one point)'),
        multi: (list) => (list.every((item) => item.delta < 0) ? `the nearest station would have done slightly better, by ${upTo(list.map((item) => item.delta))}` : 'the nearest would have done practically as well') },
      { items: worse, single: (list) => `the nearest station would actually have scored higher, by ${upTo(list.map((item) => item.delta))}`, multi: (list) => `the nearest station would actually have scored higher, by ${upTo(list.map((item) => item.delta))}` },
    ].filter((group) => group.items.length);
    const note = (group, form) => {
      if (group.silent) return '';
      const current = usingNearest(group.items);
      if (!current) return '';
      explain = true;
      if (current === group.items.length) return form === 'single' ? ', and it is also the station in use for the coming season' : ' (and it is also the station in use for the coming season)';
      return ` (${count(current)} of the ${count(group.items.length)} use the nearest station for the coming season)`;
    };
    if (groups.length === 1) {
      const [group] = groups;
      out.push(' For ', ...joinNames(group.items), ` ${group.single(group.items)}${note(group, 'single')}.`);
    } else {
      out.push(better.length ? ` Choosing a station by past performance rather than distance helped in ${count(better.length)} of the ${count(scored.length)} counties: ` : ' Choosing a station by past performance rather than distance did not help here: ');
      groups.forEach((group, index) => {
        if (index > 0) out.push(index === groups.length - 1 ? '; and ' : '; ');
        out.push('in ', ...joinNames(group.items), ` ${group.multi(group.items)}${note(group, 'multi')}`);
      });
      out.push('.');
    }
  }
  if (explain) out.push(' Where the station in use is the nearest one, the gain figure reflects earlier seasons in which the past-performance choice picked a different station.');
  return out;
}

function notesList(items) {
  const notes = items.flatMap((item) => {
    const name = countyLabel(item.county, item.fips); const out = [];
    if (item.stationNote) out.push(`${name}: ${item.stationNote}`);
    return out;
  });
  if (!notes.length) return null;
  const list = node('ul', undefined, { class: 'notes' }); notes.forEach((text) => list.append(node('li', text))); return list;
}

/** The one-line summary beside the heading: how many counties were scored, on which seasons. */
function seasonsSummary(items) {
  const evaluated = items.filter((item) => item.evaluable && item.seasons != null);
  const total = items.length; const left = total - evaluated.length;
  if (!evaluated.length) return `None of these ${num(total)} counties could be scored — see each row.`;
  const ranges = new Set(evaluated.map((item) => `${item.seasons}|${seasonRange(item.seasonList)}`));
  const who = left === 0 ? `All ${num(total)} counties` : `${num(evaluated.length)} of ${num(total)} counties`;
  const on = ranges.size === 1 ? `evaluated on ${num(evaluated[0].seasons)} matched seasons (${seasonRange(evaluated[0].seasonList)})` : 'evaluated on differing sets of matched seasons (see the last column)';
  return left === 0 ? `${who} ${on}` : `${who} ${on}; ${num(left)} could not be scored — see ${left === 1 ? 'its row' : 'their rows'}.`;
}

/* ---------- joint weather section ---------- */
/** Cell tint from the design tokens: --teal #195d70 for positive, --accent #c2543a for negative. */
function tint(value) {
  if (!finite(value)) return '';
  const v = Math.max(-1, Math.min(1, Number(value)));
  return v >= 0 ? `background:rgba(25,93,112,${(v * 0.45).toFixed(2)})` : `background:rgba(194,84,58,${(-v * 0.45).toFixed(2)})`;
}

/** Heading and unit kept apart so the unit can be dropped on a narrow screen. */
const STATS_HEADERS = [['County'], ['Mean', '(degree days)'], ['Standard deviation', '(degree days)']];

function correlationTable(joint, countyFor) {
  const wrap = node('div', undefined, { class: 'table-wrap' });
  const table = node('table', undefined, { class: 'metric-table corr-table', 'aria-label': 'Correlation between the counties’ simulated indices' });
  const head = node('thead'); const headRow = node('tr'); headRow.append(node('th', 'County', { scope: 'col' }));
  joint.ids.forEach((fips) => headRow.append(node('th', countyFor(fips)?.name || fips, { scope: 'col', class: 'num' })));
  head.append(headRow);
  const body = node('tbody');
  joint.ids.forEach((fips, row) => {
    const tr = node('tr'); tr.append(node('th', countyLabel(countyFor(fips), fips), { scope: 'row' }));
    joint.correlation[row].forEach((value, column) => tr.append(node('td', ratio(value, 2), { class: `num corr-cell${row === column ? ' corr-self' : ''}`, style: tint(value) })));
    body.append(tr);
  });
  table.append(head, body); wrap.append(table); return wrap;
}

function jointSection(joint, ids, indexId, countyFor) {
  const section = node('div', undefined, { class: 'stack' });
  section.append(node('h3', 'How their weather moves together'));
  if (!joint) { section.append(node('p', 'No shared weather scenarios are available for at least two of these counties, so no joint summary is shown.', { class: 'status' })); return section; }
  if (joint.error) { section.append(node('p', joint.error, { class: 'status' })); return section; }
  const label = pairLabel(indexId);
  section.append(node('p', `Across ${num(joint.count)} simulated ${label} outcomes drawn from one shared weather scenario set, this is how much each county's index typically moves, in degree days, and how closely the counties move together. It is descriptive only: no hedge, loss or pooled figure is inferred from it.`, { class: 'status' }));
  const stats = dataTable(STATS_HEADERS.map((parts) => parts.join(' ')), joint.ids.map((fips, index) => [countyLabel(countyFor(fips), fips), num(joint.stats[index].mean), num(joint.stats[index].sd)]), { numeric: [1, 2] });
  stats.classList.add('compare-stats');
  // The unit rides in a span so a phone can drop it (compare.css); the sentence above still gives it.
  stats.querySelectorAll('thead th').forEach((cell, index) => {
    const [heading, unit] = STATS_HEADERS[index];
    if (!unit) return;
    cell.textContent = heading;
    cell.append(document.createTextNode(' '), node('span', unit, { class: 'col-unit' }));
  });
  section.append(scrollHint('This table is wider than the page. Scroll it sideways to see every column.'), stats);
  section.append(node('p', 'Correlation of the counties’ simulated indices: 1.00 means they move in lockstep, 0 means no relation. Deeper teal marks a stronger positive relation; rust would mark a negative one. Each county against itself is 1.00 by definition.', { class: 'status' }));
  section.append(scrollHint('This table is wider than the page. Scroll it sideways to see every county.'), correlationTable(joint, countyFor));
  const missing = ids.filter((fips) => !joint.ids.includes(fips));
  if (missing.length) section.append(node('p', `${missing.map((fips) => countyLabel(countyFor(fips), fips)).join(', ')}: no weather scenarios could be loaded, so ${missing.length === 1 ? 'it is' : 'they are'} left out of this section.`, { class: 'status' }));
  return section;
}

/* ---------- index select ---------- */
function indexSelect(bootstrap, current) {
  const published = (bootstrap?.index_definitions || []).map((item) => item?.id || item?.index_id).filter((id) => pairParts(id));
  const ids = [...new Set([...published, current])].filter((id) => pairParts(id));
  const groups = { HDD: node('optgroup', undefined, { label: 'Heating degree days (cold months)' }), CDD: node('optgroup', undefined, { label: 'Cooling degree days (warm months)' }) };
  const order = (id) => { const parts = pairParts(id); return parts.kind === 'HDD' ? (parts.month + 5) % 12 : parts.month; };
  ids.sort((a, b) => order(a) - order(b)).forEach((id) => groups[pairParts(id).kind].append(node('option', pairLabel(id), { value: id })));
  const select = node('select', undefined, { id: 'compare-index' });
  Object.values(groups).filter((group) => group.childElementCount).forEach((group) => select.append(group));
  select.value = current; return select;
}

/* ---------- page ---------- */
export function mountCompare({ bootstrap, counties, scenario, loadObject, setScenario, pageLink, countyFor }) {
  const chosen = [...new Set([scenario.fips, ...String(scenario.comparisonFips || '').split(',')])].filter((fips) => /^\d{5}$/.test(fips) && countyFor(fips)).slice(0, MAX_COUNTIES);
  let latest = 0;
  let shownKey = null; // which county set and index the results panel currently shows

  /* -- controls -- */
  const form = node('form', undefined, { class: 'stack', 'aria-label': 'Choose counties and index' });
  const search = node('input', undefined, { id: 'compare-county-search', type: 'search', autocomplete: 'off', placeholder: 'Try “Dallas, TX” or 48113', role: 'combobox', 'aria-autocomplete': 'list', 'aria-expanded': 'false', 'aria-controls': 'compare-county-options' });
  const options = node('div', undefined, { id: 'compare-county-options', class: 'county-options', role: 'listbox', 'aria-label': 'County matches' });
  const searchStatus = node('p', undefined, { class: 'status', role: 'status' });
  const chips = node('ul', undefined, { class: 'chips', 'aria-label': 'Counties to compare' });
  const chipsStatus = node('p', undefined, { class: 'status' });
  const select = indexSelect(bootstrap, scenario.indexId);
  const formStatus = node('p', undefined, { id: 'compare-form-status', class: 'status', role: 'status' });
  const compare = button('Compare', { primary: true, type: 'submit', 'aria-describedby': 'compare-form-status' });

  const searchColumn = node('div');
  searchColumn.append(field('Add a county', search, 'Name, state, or five-digit FIPS code'), options, searchStatus);
  const controls = node('div', undefined, { class: 'compare-controls' });
  controls.append(searchColumn, field('Index and month', select, 'The same index is scored for every county'));
  const chosenBlock = node('div');
  chosenBlock.append(node('p', 'Chosen counties', { class: 'picker-label' }), chips, chipsStatus);
  const actions = node('div', undefined, { class: 'btn-row' }); actions.append(compare, formStatus);
  form.append(controls, chosenBlock, actions);

  const controlPanel = node('section', undefined, { class: 'panel', 'aria-label': 'Choose counties' });
  const controlHead = node('div', undefined, { class: 'panel-head' });
  controlHead.append(node('h2', 'Choose counties'), node('p', `Two to six counties, scored on the same index. ${scenario.comparisonFips ? 'The counties in your link are already added.' : 'Your current county is already added.'}`));
  controlPanel.append(controlHead, form);

  /* -- results -- */
  const resultPanel = node('section', undefined, { class: 'panel', 'aria-label': 'Comparison results' });
  const results = node('div', undefined, { 'aria-live': 'polite' });
  resultPanel.append(results);
  replacePanel('.lab-panel', [controlPanel, resultPanel]);

  /* -- picker behaviour -- */
  let matches = []; let active = -1;
  const optionId = (index) => `compare-county-options-option-${index}`;
  const currentKey = () => `${chosen.join(',')}|${scenario.indexId}`;
  /** The Compare button is always focusable; its state is spelled out in the status beside it. */
  function syncButton() {
    const count = chosen.length; const ready = count >= MIN_COUNTIES;
    compare.textContent = ready ? `Compare ${count} counties` : 'Compare';
    compare.setAttribute('aria-disabled', String(!ready));
    formStatus.textContent = ready ? '' : count === 0 ? 'Choose two or more counties to compare.' : 'Add one more county to compare.';
    // The panel below must not keep telling the reader to add a county they have already added.
    if (!shownKey) showEmpty();
    else if (shownKey === null) formStatus.textContent = `Press Compare to score these ${count} counties on ${pairLabel(scenario.indexId)}.`;
    else if (shownKey !== currentKey()) formStatus.textContent = 'The table below still shows the previous set. Press Compare to update it.';
    else formStatus.textContent = '';
  }
  function renderChips() {
    chips.replaceChildren();
    chosen.forEach((fips) => {
      const item = node('li', undefined, { class: 'chip' });
      const label = countyLabel(countyFor(fips), fips);
      item.append(node('span', label));
      const remove = node('button', '×', { type: 'button', class: 'chip-remove', 'aria-label': `Remove ${label}` });
      remove.addEventListener('click', () => {
        const position = chosen.indexOf(fips); chosen.splice(position, 1);
        renderChips(); renderMatches();
        searchStatus.textContent = `${label} removed.`;
        const next = chips.querySelectorAll('.chip-remove')[Math.min(position, chosen.length - 1)];
        (next || search).focus();
      });
      item.append(remove); chips.append(item);
    });
    const count = chosen.length;
    chipsStatus.textContent = count === 0 ? 'No counties chosen yet.' : count >= MAX_COUNTIES ? `${count} of ${MAX_COUNTIES} chosen. Remove one to add another.` : `${count} of ${MAX_COUNTIES} chosen.`;
    syncButton();
  }
  function renderMatches() {
    options.replaceChildren();
    matches.forEach((county, index) => {
      const added = chosen.includes(county.fips);
      const option = node('button', undefined, { type: 'button', id: optionId(index), role: 'option', class: 'county-option', 'aria-selected': String(index === active) });
      option.append(document.createTextNode(`${county.name}, ${county.state}`), node('span', county.fips, { class: 'mono' }));
      if (added) { option.append(node('span', ' · added', { class: 'muted' })); option.disabled = true; }
      option.addEventListener('mousedown', (event) => event.preventDefault());
      option.addEventListener('click', () => add(index));
      options.append(option);
    });
    search.setAttribute('aria-expanded', String(matches.length > 0));
    if (active >= 0) search.setAttribute('aria-activedescendant', optionId(active)); else search.removeAttribute('aria-activedescendant');
  }
  function runSearch() {
    const all = findCountyMatches(counties, search.value);
    matches = all.slice(0, MAX_MATCHES); active = matches.length === 1 ? 0 : -1;
    renderMatches();
    if (!search.value.trim()) { searchStatus.textContent = ''; return; }
    searchStatus.textContent = all.length === 0 ? 'No county matches that.' : all.length > MAX_MATCHES ? `${num(all.length)} counties match; showing the first ${MAX_MATCHES}. Keep typing to narrow it down.` : `${all.length} ${all.length === 1 ? 'county matches' : 'counties match'}. Choose one to add it.`;
  }
  function add(index = active) {
    const county = matches[index];
    if (!county) { searchStatus.textContent = 'Choose a county from the matches to add it.'; return; }
    if (chosen.includes(county.fips)) { searchStatus.textContent = `${countyLabel(county, county.fips)} is already in the comparison.`; return; }
    if (chosen.length >= MAX_COUNTIES) { searchStatus.textContent = `You can compare up to ${MAX_COUNTIES} counties. Remove one to add another.`; return; }
    chosen.push(county.fips);
    search.value = ''; matches = []; active = -1; renderMatches(); renderChips();
    searchStatus.textContent = `${countyLabel(county, county.fips)} added.`;
  }
  search.addEventListener('input', runSearch);
  search.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown' && matches.length) { event.preventDefault(); active = Math.min(matches.length - 1, active + 1); renderMatches(); }
    else if (event.key === 'ArrowUp' && matches.length) { event.preventDefault(); active = Math.max(0, active - 1); renderMatches(); }
    else if (event.key === 'Enter') { event.preventDefault(); add(); }
    else if (event.key === 'Escape') { matches = []; active = -1; renderMatches(); search.value = ''; searchStatus.textContent = 'Search closed.'; }
  });

  /* -- results rendering -- */
  function showEmpty() {
    shownKey = null;
    results.replaceChildren(); results.removeAttribute('aria-busy');
    const only = chosen.length === 1 ? countyLabel(countyFor(chosen[0]), chosen[0]) : null;
    const heading = chosen.length >= MIN_COUNTIES
      ? `Press Compare to score ${count(chosen.length)} counties side by side.`
      : only ? `Add one more county to compare it with ${only}.` : 'Add two or more counties to compare them.';
    results.append(
      node('p', 'Side by side', { class: 'eyebrow' }),
      node('h2', heading),
      node('p', 'Search above by county name, state or FIPS code and choose a match to add it. Once two or more are chosen, press Compare to score them all on the same index. The link in the address bar then carries the whole set, so it can be shared.', { class: 'status' }),
    );
  }
  function showLoading(count, indexId) {
    results.replaceChildren(); results.setAttribute('aria-busy', 'true');
    results.append(node('p', 'Side by side', { class: 'eyebrow' }), node('h2', pairLabel(indexId)), node('p', `Loading ${count} counties…`, { class: 'status' }));
  }
  function showResults(items, records, ids, indexId) {
    results.replaceChildren(); results.removeAttribute('aria-busy');
    const head = node('div', undefined, { class: 'panel-head' });
    const decision = items.find((item) => item.decisionDate)?.decisionDate;
    const seasonCounts = new Set(items.filter((item) => item.evaluable && item.seasons != null).map((item) => item.seasons));
    const over = seasonCounts.size === 1 ? `over the ${num([...seasonCounts][0])} past seasons where both records exist` : 'over the past seasons where both records exist';
    head.append(node('h2', pairLabel(indexId)), node('p', seasonsSummary(items)));
    results.append(node('p', 'Side by side', { class: 'eyebrow' }), head);
    results.append(node('p', `Each county's station is the listed station that best tracked it in past seasons, not simply the nearest one. Hedge effectiveness is the share of a county's year-to-year variation in this index that hedging with that station would have removed, ${over}. Gain vs nearest is that figure minus what always using the nearest listed station would have scored; residual risk is the error left after hedging, in degree days.${decision ? ` Stations were chosen with information available as of ${dateShort(decision)}.` : ''}`, { class: 'status' }));
    results.append(scrollHint('This table is wider than the page. Scroll it sideways to see every column.'), comparisonTable(items));
    const notes = notesList(items); if (notes) results.append(notes);
    results.append(node('h3', 'What the table says', { class: 'mt' }), readingParagraph(items, indexId));
    const jointHolder = node('div', undefined, { class: 'mt-lg' });
    jointHolder.append(node('h3', 'How their weather moves together'), node('p', 'Loading the shared weather scenarios…', { class: 'status' }));
    results.append(jointHolder);
    const links = node('div', undefined, { class: 'btn-row mt-lg compare-actions' });
    links.append(download(records, ids, indexId), linkButton(`Explore ${countyLabel(countyFor(ids[0]), ids[0])} on the map`, pageLink('index.html'), { quiet: true }), linkButton('Design a contract', pageLink('contract.html'), { quiet: true }), linkButton('Build a portfolio', pageLink('portfolio.html'), { quiet: true }));
    results.append(links);
    const provenance = node('div');
    results.append(provenance);
    return { jointHolder, provenance };
  }
  function showProvenance(holder, items, records, ids, joint) {
    const loaded = records.filter((record) => record?.payload);
    const usable = joint && !joint.error ? joint : null;
    const errors = items.filter((item) => item.loadError).map((item) => `${item.fips}: ${item.loadError}`);
    if (joint?.detail) errors.push(`weather scenarios: ${joint.detail}`);
    holder.replaceChildren(provenanceBlock([
      ['Release', loaded[0]?.release_id || scenario.releaseId],
      ['County records', ids.map((fips) => `county:${fips}:${scenario.indexId}`)],
      ['Weather scenario records', usable?.ids?.length ? usable.ids.map((fips) => `county_scenarios:${fips}`) : null],
      ['Scenario set', usable?.setId],
      ['Analyses', [...new Set(loaded.map((record) => record.analysis_id).filter(Boolean))]],
      ['Data vintage', loaded[0]?.data_vintage_id],
      ['Valuation date', loaded[0]?.valuation_asof],
      ['Metric', items.find((item) => item.metricDefinition)?.metricDefinition],
      ['Interval method', items.find((item) => item.intervalMethod)?.intervalMethod],
      ['Load errors', errors.length ? errors : null],
    ]));
  }

  async function run(mode) {
    const ids = chosen.slice(0, MAX_COUNTIES);
    if (ids.length < MIN_COUNTIES) { showEmpty(); syncButton(); return; }
    setScenario({ fips: ids[0], comparisonFips: ids.slice(1).join(',') }, mode);
    const indexId = scenario.indexId; const token = ++latest;
    shownKey = `${ids.join(',')}|${indexId}`; syncButton();
    showLoading(ids.length, indexId);
    const records = await Promise.all(ids.map((fips) => loadObject(`county:${fips}:${indexId}`).catch((error) => ({ status: 'unavailable', reason_code: error.message }))));
    if (token !== latest) return;
    const items = records.map((record, index) => describeRecord(record, ids[index], countyFor(ids[index])));
    const { jointHolder, provenance } = showResults(items, records, ids, indexId);
    showProvenance(provenance, items, records, ids, null);
    requestAnimationFrame(() => syncScrollHints(results));
    let joint = null;
    try { joint = await jointWeather(ids, indexId, loadObject); }
    catch (error) { joint = { error: 'The joint weather summary could not be built for these counties.', detail: error?.message || String(error) }; }
    if (token !== latest) return;
    jointHolder.replaceChildren(jointSection(joint, ids, indexId, countyFor));
    showProvenance(provenance, items, records, ids, joint);
    requestAnimationFrame(() => syncScrollHints(results));
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (chosen.length < MIN_COUNTIES) { syncButton(); search.focus(); return; }
    run();
  });
  select.addEventListener('change', () => {
    setScenario({ indexId: select.value });
    if (chosen.length >= MIN_COUNTIES) run('replaceState'); else { showEmpty(); syncButton(); }
  });

  window.addEventListener('resize', () => syncScrollHints(results));
  renderChips();
  if (chosen.length >= MIN_COUNTIES) run('replaceState'); else showEmpty();
}
