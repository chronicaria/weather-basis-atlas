import { createPayloadClient } from '../data/client.js';
import { mountCountyCombobox } from '../controls/county-combobox.js';
import { rampCss, renderAtlasMap } from '../charts/atlas-map.js';
import { drawHistogram, drawScatter } from '../charts/simple-charts.js';
import { decodeScenario, encodeScenario, normalizeScenario } from '../state/scenario.js';
import { createSelectionController } from '../state/selection.js';
import { mountCompare } from './compare.js';
import { mountContract } from './contract.js';
import { mountPortfolio } from './portfolio.js';
import { mountResearch } from './research.js';
import { node } from './render.js';
import {
  LAYER_ORDER, NA, button, countyLabel, dataTable, dateShort, envelopeProvenance, km, layerMeta, linkButton, num, pairLabel, pairParts, pct, pts, seasonRange, stationCity, stationColor, stationLabel, statusText, tile, tiles,
} from './format.js';

const $ = (selector) => document.querySelector(selector);
const publicRoot = document.documentElement.dataset.publicRoot || (location.pathname.includes('/research/') ? '..' : '.');
const client = createPayloadClient({ baseUrl: `${publicRoot}/data/v2` });
/** The scenario object is mutated in place so every page module shares one live view of it. */
const scenario = {};
let selection;
let counties = [];
let bootstrap;
let summaryCache = new Map();

function routePath(route = document.body.dataset.route || 'index.html') {
  return route === 'research/index.html' ? location.pathname.replace(/research\/[^/]*$/, 'research/index.html') : location.pathname.replace(/[^/]*$/, route);
}
function replaceUrl(next, mode = 'pushState') { history[mode]({ scenario: { ...next } }, '', `${routePath()}${encodeScenario({ ...next, route: document.body.dataset.page })}`); }
function setScenario(patch, mode) { Object.assign(scenario, normalizeScenario({ ...scenario, ...patch })); replaceUrl(scenario, mode); renderContext(); }
const loadObject = (objectId, signal) => client.object(bootstrap, objectId, signal);
const countyFor = (fips) => counties.find((c) => c.fips === String(fips).padStart(5, '0'));
function pageLink(route, patch = {}) { const prefix = document.body.dataset.page === 'research' ? '../' : ''; return `${prefix}${route}${encodeScenario({ ...scenario, ...patch, route: route.startsWith('compare') ? 'compare' : route.startsWith('contract') ? 'contract' : route.startsWith('portfolio') ? 'portfolio' : route.startsWith('research') ? 'research' : 'explore' })}`; }

function renderContext() {
  const list = $('#context-items'); if (!list) return; list.replaceChildren();
  const items = [['County', countyLabel(countyFor(scenario.fips), scenario.fips)], ['Index', pairLabel(scenario.indexId)], ['Valued as of', dateShort(bootstrap?.defaults?.valuation_asof || scenario.valuationAsOf)]];
  if (document.body.dataset.page === 'contract' && scenario.strike != null) items.push(['Payoff', `${scenario.payoffFamily.replaceAll('_', ' ')} · strike ${num(scenario.strike)}`]);
  items.forEach(([label, value]) => { const item = node('div'); item.append(node('dt', label), node('dd', value)); list.append(item); });
}

function populateIndexOptions() {
  const select = $('#index'); if (!select) return;
  const ids = bootstrap.objects.map((item) => item.object_key || item.object_id).filter((id) => id?.startsWith('summary:')).map((id) => id.slice('summary:'.length));
  if (!ids.length) return;
  const groups = { HDD: node('optgroup', undefined, { label: 'Heating degree days (cold months)' }), CDD: node('optgroup', undefined, { label: 'Cooling degree days (warm months)' }) };
  const order = (id) => { const parts = pairParts(id); return parts ? (parts.kind === 'HDD' ? (parts.month + 5) % 12 : parts.month) : 99; };
  ids.sort((a, b) => order(a) - order(b)).forEach((id) => { const parts = pairParts(id); const option = node('option', pairLabel(id), { value: id }); (groups[parts?.kind] || groups.HDD).append(option); });
  select.replaceChildren(groups.HDD, groups.CDD); if (ids.includes(scenario.indexId)) select.value = scenario.indexId;
}

/* ---------- Explore: county record ---------- */
function renderCountyDetails(record) {
  const facts = $('#county-facts'); if (!facts) return; facts.replaceChildren();
  const payload = record?.payload || {}; const county = payload.county || {}; const matched = payload.matched_policy || {}; const asof = payload.selection_asof || {}; const availability = payload.current_availability || {}; const historical = payload.historical_evidence || {};
  const alternatives = Array.isArray(payload.alternatives) ? payload.alternatives : [];
  const selectedStation = asof.station_id || asof.station_name; const selectedMeta = alternatives.find((item) => item.station_id === asof.station_id || item.station_name === asof.station_name);
  const nearest = [...alternatives].sort((a, b) => (a.distance_km ?? Infinity) - (b.distance_km ?? Infinity))[0];
  const evaluable = historical.status === 'evaluable' && matched.metric?.value != null;
  const summary = node('p', undefined, { class: 'status' });
  summary.textContent = evaluable
    ? `Evaluated on ${num(matched.n_common)} matched seasons (${seasonRange(matched.common_seasons)}). Station chosen as of ${dateShort(asof.decision_time || asof.valuation_date)} using observations through ${dateShort(asof.observation_cutoff)}, for the ${pairLabel(scenario.indexId)} window ${dateShort(asof.observation_start)} – ${dateShort(asof.observation_end)}.`
    : `${statusText(historical)} ${matched.reason_code ? statusText(matched.reason_code) : ''}`.trim();
  facts.append(summary);
  if (availability.status && availability.status !== 'eligible_modeled_proxy') facts.append(node('p', statusText(availability), { class: 'callout callout-warn' }));
  const interval = matched.interval || {};
  facts.append(tiles([
    tile('Selected listed station', selectedStation ? stationCity(selectedStation) : NA, selectedStation ? `${stationLabel(selectedStation).split(' · ')[1] || ''}${selectedMeta?.distance_km != null ? ` · ${km(selectedMeta.distance_km)} away` : ''} · chosen by the prior-best rule` : statusText(availability), { small: true, na: !selectedStation }),
    tile('Hedge effectiveness', pct(matched.metric?.value), evaluable ? 'share of index variation removed by the hedge' : statusText(matched.reason_code)),
    tile('Gain vs nearest station', pts(matched.delta_he), matched.nearest_he != null ? `nearest${nearest ? ` (${stationCity(nearest.station_id || nearest.station_name)})` : ''} scores ${pct(matched.nearest_he)}${interval.low != null ? ` · 95% band ${pts(interval.low)} to ${pts(interval.high)}` : ''}` : NA),
    tile('Residual risk', matched.residual_rmse_degree_days != null ? num(matched.residual_rmse_degree_days) : NA, 'degree days of error left after hedging (RMSE)'),
    tile('Selection stability', pct(matched.selection_stability, 0), 'how often the same station was chosen historically'),
  ]));
  if (selectedStation) facts.append(renderSimulation(county.fips || scenario.fips, scenario.indexId, selectedStation));
  if (alternatives.length) {
    const rows = [...alternatives].sort((a, b) => (b.historical_he ?? -Infinity) - (a.historical_he ?? -Infinity)).map((item, index) => {
      const id = item.station_id || item.station_name; const isSelected = id === asof.station_id || item.station_name === asof.station_name; const bar = node('span', undefined, { class: `bar${(item.historical_he ?? 0) < 0 ? ' neg' : ''}`, style: `width:${Math.min(100, Math.abs(item.historical_he ?? 0) * 60)}px` });
      const heCell = node('span'); heCell.append(bar, document.createTextNode(pct(item.historical_he)));
      const name = node('span'); name.append(node('i', undefined, { style: `display:inline-block;width:.6rem;height:.6rem;border-radius:2px;margin-right:.45rem;background:${stationColor(id)}` }), document.createTextNode(stationLabel(id)));
      if (isSelected) name.append(node('span', ' · selected', { class: 'small', style: 'color:var(--ink-2)' }));
      const row = [index + 1, name, heCell, km(item.distance_km), num(item.n_test)]; row.__class = isSelected ? 'is-selected' : (item.n_test != null && item.n_test < 20 ? 'is-muted' : ''); return row;
    });
    const section = node('div'); const scrollNote = node('p', 'This table is wider than the page. Scroll it sideways to see every column.', { class: 'status', hidden: 'hidden' });
    section.append(node('h3', 'Rough ranking of the thirteen stations'), node('p', 'These percentages come from the first edition of the atlas, measured over each station\'s whole record rather than the 45 seasons this county and station share. They are not comparable with the figure above and are shown only to order which stations are worth looking at.', { class: 'status' }), scrollNote, dataTable(['#', 'Station', 'First-edition score', 'Distance', 'Seasons'], rows, { numeric: [0, 3, 4] }));
    const wrap = section.querySelector('.table-wrap');
    if (wrap) { wrap.tabIndex = 0; wrap.setAttribute('role', 'region'); wrap.setAttribute('aria-label', 'Station ranking, scrollable'); requestAnimationFrame(() => { scrollNote.hidden = !(wrap.scrollWidth > wrap.clientWidth + 1); }); }
    facts.append(section);
  }
  const actions = node('div', undefined, { class: 'btn-row mt' });
  actions.append(linkButton('Compare with other counties', pageLink('compare.html')), linkButton('Design a contract here', pageLink('contract.html'), { primary: true }), linkButton('Add to a portfolio', pageLink('portfolio.html')));
  facts.append(actions);
  facts.append(envelopeProvenance(record, [['County FIPS', county.fips || scenario.fips], ['Selection policy', asof.policy_id], ['Selection record', asof.selection_id], ['Score tape', asof.score_tape_id], ['Interval method', interval.method], ['Metric', matched.metric?.definition], ['Comparison', matched.comparison_id]]));
}

/** Simulated-season charts for the county and its selected station (2,000 aligned paths). */
let stationScenarios;
function matrixColumn(envelope, entityId) { const matrix = envelope?.payload?.matrix; const column = matrix?.entity_ids?.indexOf(entityId); return column == null || column < 0 ? null : matrix.values.map((row) => row[column]); }
function quantile(sorted, q) { const position = (sorted.length - 1) * q; const low = Math.floor(position); return sorted[low] + (sorted[Math.min(sorted.length - 1, low + 1)] - sorted[low]) * (position - low); }
function renderSimulation(fips, pairId, stationEntity) {
  const section = node('div'); section.append(node('h3', 'What the simulation says'));
  const note = node('p', 'Loading 2,000 simulated seasons…', { class: 'status' }); section.append(note);
  const grid = node('div', undefined, { class: 'chart-grid' });
  const histogram = node('canvas', undefined, { width: '1040', height: '440', 'aria-label': `Distribution of simulated ${pairLabel(pairId)} for this county` }); const scatter = node('canvas', undefined, { width: '1040', height: '440', 'aria-label': 'Simulated county index against the selected station index' });
  const figureA = node('figure'); const captionA = node('figcaption', ''); figureA.append(histogram, captionA); const figureB = node('figure'); const captionB = node('figcaption', ''); figureB.append(scatter, captionB); grid.append(figureA, figureB); section.append(grid);
  const stationId = String(stationEntity).split(':')[0];
  stationScenarios ||= loadObject('station_scenarios');
  Promise.all([loadObject(`county_scenarios:${fips}`), stationScenarios]).then(([countyRecord, stationRecord]) => {
    if (fips !== selection?.committedFips || pairId !== scenario.indexId) return;
    const countyValues = matrixColumn(countyRecord, `${fips}:${pairId}`); const stationValues = matrixColumn(stationRecord, `${stationId}:${pairId}`);
    if (!countyValues) { note.textContent = 'No simulated seasons are published for this county and month.'; grid.remove(); return; }
    const sorted = [...countyValues].sort((a, b) => a - b); const median = quantile(sorted, 0.5); const low = quantile(sorted, 0.05); const high = quantile(sorted, 0.95);
    captionA.textContent = `${num(countyValues.length)} simulated seasons of ${pairLabel(pairId)} for this county: the median is ${num(median)} degree days and nine seasons in ten fall between ${num(low)} and ${num(high)}.`;
    note.textContent = `Simulated from the county's own temperature history at the July 2026 valuation date; these paths are what the Contract Lab prices on.`;
    if (!stationValues) figureB.replaceChildren(node('p', 'No aligned simulation is published for the selected station.', { class: 'status' }));
    // Draw at the size the chart is actually shown, so tick labels stay legible on a phone.
    const draw = () => {
      const width = Math.max(260, Math.round(figureA.clientWidth || 520)); const height = Math.round(Math.max(180, Math.min(240, width * 0.45)));
      drawHistogram(histogram, countyValues, { width, height, xLabel: `${pairLabel(pairId, { short: true })} for the county, degree days`, markers: [{ value: median, label: `median ${num(median)}` }] });
      if (!stationValues) return;
      const fit = drawScatter(scatter, stationValues, countyValues, { width, height, xLabel: `${stationCity(stationId)} station index, degree days`, yLabel: 'County index, degree days' });
      captionB.textContent = `Each dot is one simulated season. The county index and the ${stationCity(stationId)} index move together with correlation ${fit ? fit.r.toFixed(2) : NA}; the closer the dots hug the line, the better a contract on that station tracks this county.`;
    };
    draw();
    if (window.ResizeObserver) { let last = figureA.clientWidth; new ResizeObserver(() => { if (Math.abs(figureA.clientWidth - last) > 24) { last = figureA.clientWidth; draw(); } }).observe(figureA); }
  }).catch((error) => { note.textContent = `Simulated seasons are unavailable: ${error.message}`; grid.remove(); });
  return section;
}

function showCounty(state) {
  const name = $('#county-name'); const status = $('#county-load-status'); const retry = $('#retry-county');
  if (!name || !status) return;
  if (state.phase === 'loading') { status.textContent = `Loading ${countyLabel(countyFor(state.committedFips), state.committedFips)}…`; retry?.classList.add('hidden'); return; }
  if (state.phase === 'error') {
    const label = countyLabel(countyFor(state.committedFips), state.committedFips);
    name.textContent = label;
    $('#county-facts')?.replaceChildren();
    status.textContent = countyFor(state.committedFips)
      ? `${label} could not be loaded. ${state.error.message}`
      : `${label} is not part of this study, which covers the counties of the contiguous United States.`;
    status.classList.add('status-error'); retry?.classList.toggle('hidden', !countyFor(state.committedFips)); return;
  }
  status.classList.remove('status-error'); retry?.classList.add('hidden');
  const county = state.payload?.payload?.county || countyFor(state.committedFips);
  name.replaceChildren(document.createTextNode(countyLabel(county, state.committedFips)), node('span', ` FIPS ${state.committedFips}`, { class: 'muted small', style: 'font-family:var(--sans);font-weight:400;margin-left:.6rem;font-size:.85rem' }));
  status.textContent = '';
  renderCountyDetails(state.payload);
  renderContext();
}

/* ---------- Explore: map, legend, headline, table ---------- */
function layerRows(rows, key) { return rows.map((row) => { const layer = row.layers?.[key]; return { fips: row.fips, value: layer && typeof layer === 'object' ? layer.value ?? null : layer ?? null }; }); }
function renderLegend(layer, domain, rows) {
  const legend = $('#map-legend'); if (!legend) return; legend.replaceChildren();
  $('#layer-help').textContent = layer.help;
  if (layer.kind === 'category') {
    const counts = new Map(); rows.forEach(({ value }) => { if (value != null) counts.set(value, (counts.get(value) || 0) + 1); });
    const swatches = node('div', undefined, { class: 'swatches' });
    [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 14).forEach(([value, count]) => { const item = node('span', undefined, { class: 'swatch', title: `${layer.format(value)} · ${num(count)} counties` }); item.append(node('i', undefined, { style: `background:${stationColor(value)}` }), node('span', `${layer.format(value)} (${num(count)})`)); swatches.append(item); });
    const missing = rows.filter(({ value }) => value == null).length; if (missing) { const item = node('span', undefined, { class: 'swatch missing' }); item.append(node('i'), node('span', `No proxy (${num(missing)})`)); swatches.append(item); }
    legend.append(swatches); return;
  }
  legend.append(node('div', undefined, { class: 'ramp', style: `background:${rampCss(layer)}` }));
  const labels = node('div', undefined, { class: 'ramp-labels' }); labels.append(node('span', layer.format(domain.min)), layer.kind === 'diverging' ? node('span', layer.format(0)) : node('span', layer.format((domain.min + domain.max) / 2)), node('span', layer.format(domain.max))); legend.append(labels);
  const missing = rows.filter(({ value }) => !Number.isFinite(value)).length; const note = node('span', undefined, { class: 'swatch missing' }); note.append(node('i'), node('span', missing ? `Grey: no value (${num(missing)} counties)` : 'Grey: no value')); legend.append(note);
}
function renderHeadline(rows, pairId) {
  const target = $('#headline-finding'); if (!target) return;
  const he = layerRows(rows, 'matched_he').map((r) => r.value).filter(Number.isFinite); const delta = layerRows(rows, 'delta_he').map((r) => r.value).filter(Number.isFinite);
  if (!he.length) { target.textContent = `No matched evidence is published for ${pairLabel(pairId)}.`; return; }
  const sorted = [...he].sort((a, b) => a - b); const median = sorted[Math.floor(sorted.length / 2)]; const half = he.filter((v) => v >= 0.5).length / he.length; const better = delta.filter((v) => v > 0).length / (delta.length || 1); const worse = delta.filter((v) => v < 0).length / (delta.length || 1);
  target.textContent = `For ${pairLabel(pairId)}, the selected listed station removes at least half of the county's index variation in ${pct(half, 0)} of counties (median ${pct(median, 0)}). Choosing a station by past performance beat simply taking the nearest one in ${pct(better, 0)} of counties and did worse in ${pct(worse, 0)}.`;
}
function renderCountyTable(rows, layer) {
  const panel = $('#county-table-panel'); if (!panel) return; panel.replaceChildren();
  const details = node('details', undefined, { class: 'plain' }); details.append(node('summary', `Browse all ${num(rows.length)} counties by ${layer.name.toLowerCase()}`));
  const input = node('input', undefined, { type: 'search', class: 'control', placeholder: 'Filter by county, state, or FIPS', 'aria-label': 'Filter county table', style: 'max-width:22rem' });
  const holder = node('div', undefined, { class: 'mt' }); const values = layerRows(rows, layer.key);
  const draw = () => { const query = input.value.trim().toLowerCase(); const matches = values.filter(({ fips }) => { const county = countyFor(fips); return !query || `${county?.name || ''} ${county?.state || ''} ${fips}`.toLowerCase().includes(query); }); const sorted = layer.kind === 'category' ? matches : [...matches].sort((a, b) => (Number.isFinite(b.value) ? b.value : -Infinity) - (Number.isFinite(a.value) ? a.value : -Infinity)); const shown = sorted.slice(0, 150); holder.replaceChildren(node('p', `${num(matches.length)} count${matches.length === 1 ? 'y' : 'ies'}${shown.length < matches.length ? `, showing the first ${shown.length}` : ''}`, { class: 'status' }), dataTable(['County', 'FIPS', layer.name], shown.map(({ fips, value }) => { const county = countyFor(fips); const link = node('a', countyLabel(county, fips), { href: '#', 'data-fips': fips }); link.addEventListener('click', (event) => { event.preventDefault(); setScenario({ fips }); selection.commit(fips); window.scrollTo({ top: 0, behavior: 'smooth' }); }); return [link, fips, layer.format(value)]; }), { numeric: [2] })); };
  input.addEventListener('input', draw); details.append(input, holder); details.addEventListener('toggle', () => { if (details.open && !holder.hasChildNodes()) draw(); }); panel.append(details);
}
async function loadSummary(pairId) { if (!summaryCache.has(pairId)) summaryCache.set(pairId, loadObject(`summary:${pairId}`)); return summaryCache.get(pairId); }

async function initializeExplore() {
  const status = $('#county-search-status');
  selection = createSelectionController({ initialFips: scenario.fips, loadCounty: (fips, signal) => client.object(bootstrap, `county:${fips}:${scenario.indexId}`, signal), onChange: showCounty });
  mountCountyCombobox({ input: $('#county-search'), listbox: $('#county-options'), status, counties, selectedFips: scenario.fips, onCommit: async (fips) => { setScenario({ fips }); await selection.commit(fips); } });
  $('#retry-county')?.addEventListener('click', () => selection.commit(selection.committedFips));
  const map = $('#atlas-map'); const tooltip = $('#map-tooltip'); let activeLayer = null; let rows = []; let layers = [];
  const describe = (fips) => { const county = countyFor(fips); const value = rows.find((row) => row.fips === fips)?.layers?.[activeLayer.key]; const scalar = value && typeof value === 'object' ? value.value : value; return `${countyLabel(county, fips)} — ${activeLayer.name}: ${activeLayer.format(scalar)}`; };
  const paint = async () => {
    if (!map || !activeLayer) return;
    const values = layerRows(rows, activeLayer.key);
    try { const { domain } = await renderAtlasMap(map, { topologyUrl: 'assets/vendor/counties-albers-10m.json', rows: values, layer: activeLayer, selectedFips: selection.committedFips, tooltip, describe, onSelect: async (fips) => { setScenario({ fips }); await selection.commit(fips); paint(); } }); renderLegend(activeLayer, domain, values); $('#map-status').textContent = `${activeLayer.name} · ${pairLabel(scenario.indexId)}`; }
    catch (error) { $('#map-status').textContent = error.message; }
    renderCountyTable(rows, activeLayer);
  };
  const buildLayerButtons = () => { const holder = $('#layer-buttons'); holder.replaceChildren(); layers.forEach((layer) => { const control = node('button', layer.name, { type: 'button', 'aria-pressed': String(layer.key === activeLayer?.key), title: layer.help }); control.addEventListener('click', () => { activeLayer = layer; [...holder.children].forEach((item) => item.setAttribute('aria-pressed', String(item === control))); paint(); }); holder.append(control); }); };
  const loadPair = async () => {
    $('#map-status').textContent = 'Loading the national summary…';
    try {
      const summary = await loadSummary(scenario.indexId); rows = summary.payload?.rows || summary.payload?.counties || [];
      const sample = rows[0]?.layers || {}; const keys = [...new Set(rows.flatMap((row) => Object.keys(row.layers || {})))].sort((a, b) => (LAYER_ORDER.indexOf(a) + 100) % 100 - (LAYER_ORDER.indexOf(b) + 100) % 100);
      const informative = (key) => new Set(rows.map((row) => { const layer = row.layers?.[key]; return layer && typeof layer === 'object' ? layer.value : layer; })).size > 1;
      layers = keys.filter(informative).map((key) => layerMeta(key, sample[key])); activeLayer = layers.find((layer) => layer.key === activeLayer?.key) || layers[0] || null;
      buildLayerButtons(); renderHeadline(rows, scenario.indexId); await paint();
    } catch (error) { $('#map-status').textContent = error.message; }
  };
  $('#index')?.addEventListener('change', async (event) => { setScenario({ indexId: event.target.value }); await Promise.all([selection.commit(selection.committedFips), loadPair()]); });
  await Promise.all([selection.commit(scenario.fips), loadPair()]);
}

/* ---------- shared ---------- */
function bindSharedControls() {
  $('#copy-scenario')?.addEventListener('click', async () => { try { await navigator.clipboard.writeText(location.href); $('#scenario-status').textContent = 'Link copied. It opens this exact view, pinned to this release.'; } catch { $('#scenario-status').textContent = `Copy this link: ${location.href}`; } });
  $('#reset-scenario')?.addEventListener('click', () => { location.href = routePath(); });
  window.addEventListener('popstate', () => { const decoded = decodeScenario(); if (decoded.scenario) location.reload(); });
}
async function start() {
  const decoded = decodeScenario();
  if (decoded.error) { $('#scenario-status').textContent = decoded.error; return; }
  Object.assign(scenario, decoded.scenario);
  if (!scenario.releaseId) {
    const pointer = await client.current();
    if (!pointer?.release_id) throw new Error('The current release pointer has no release identity.');
    Object.assign(scenario, normalizeScenario({ ...scenario, releaseId: pointer.release_id }));
    replaceUrl(scenario, 'replaceState');
  }
  bootstrap = await client.bootstrap(scenario.releaseId);
  counties = (bootstrap.county_registry || bootstrap.objects.find((item) => item.result_type === 'county_registry')?.payload?.counties || []).map((county) => ({ ...county, fips: String(county.fips).padStart(5, '0') }));
  if (bootstrap.capabilities?.scope === 'artificial_fixture') $('#scenario-status').textContent = 'This is an artificial numerical fixture for browser and solver checks, not weather evidence.';
  if (decoded.legacy) $('#scenario-status').textContent = 'This is a link to the original V1 release. Open the V1 archive from the footer to see that result.';
  populateIndexOptions(); renderContext(); bindSharedControls();
  const shared = { bootstrap, counties, scenario, loadObject, setScenario, pageLink, countyFor };
  if (document.body.dataset.page === 'explore') await initializeExplore();
  if (document.body.dataset.page === 'compare') await mountCompare(shared);
  if (document.body.dataset.page === 'contract') await mountContract(shared);
  if (document.body.dataset.page === 'portfolio') await mountPortfolio(shared);
  if (document.body.dataset.page === 'research') await mountResearch(shared);
}
start().catch((error) => { const status = $('#scenario-status'); if (status) { status.textContent = `The atlas could not start: ${error.message}`; status.classList.add('status-error'); } console.error(error); });
