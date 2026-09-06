import { createPayloadClient } from '../data/client.js';
import { mountCountyCombobox } from '../controls/county-combobox.js';
import { renderAtlasMap } from '../charts/atlas-map.js';
import { decodeScenario, encodeScenario, normalizeScenario, scenarioLabel } from '../state/scenario.js';
import { createSelectionController } from '../state/selection.js';
import { mountCompare } from './compare.js';
import { mountContract } from './contract.js';
import { mountPortfolio } from './portfolio.js';
import { mountResearch } from './research.js';

const $ = (selector) => document.querySelector(selector);
const publicRoot = document.documentElement.dataset.publicRoot
  || (location.pathname.includes('/research/') ? '..' : '.');
const client = createPayloadClient({ baseUrl: `${publicRoot}/data/v2` });
let scenario;
let selection;
let counties = [];
let bootstrap;

function replaceUrl(next, mode = 'pushState') {
  const route = document.body.dataset.route || 'index.html';
  const routePath = route === 'research/index.html'
    ? location.pathname.replace(/research\/[^/]*$/, 'research/index.html')
    : location.pathname.replace(/[^/]*$/, route);
  history[mode]({ scenario: next }, '', `${routePath}${encodeScenario({ ...next, route: document.body.dataset.page })}`);
}
function setScenario(patch, mode) { scenario = normalizeScenario({ ...scenario, ...patch }); replaceUrl(scenario, mode); renderScenarioSummary(); }
const loadObject = (objectId, signal) => client.object(bootstrap, objectId, signal);
function renderScenarioSummary() { const target = $('#scenario-summary'); if (target) target.textContent = `Scenario: ${scenarioLabel(scenario)} · release ${scenario.releaseId}`; }
function populateIndexOptions() { const select = $('#index'); if (!select) return; const ids = bootstrap.objects.map((item) => item.object_key || item.object_id).filter((id) => id?.startsWith('summary:')).map((id) => id.slice('summary:'.length)); if (!ids.length) return; select.replaceChildren(...ids.sort().map((id) => { const option = document.createElement('option'); option.value = id; option.textContent = id; return option; })); if (ids.includes(scenario.indexId)) select.value = scenario.indexId; }
function countyTitle(payload, fips) { return payload?.meta?.county_name || payload?.meta?.name || counties.find((c) => c.fips === fips)?.name || fips; }
function display(value) { if (value == null) return 'Unavailable'; if (typeof value === 'object') return value.label || value.reason_code ? `${value.label || value.status || 'unavailable'}${value.reason_code ? `: ${value.reason_code}` : ''}` : JSON.stringify(value); return String(value); }
function layerScalar(layer) { return layer && typeof layer === 'object' ? layer.value ?? null : layer ?? null; }
function layerKind(rows, layer) { const values = rows.map((row) => layerScalar(row.layers?.[layer])).filter((value) => value != null); return values.length && values.every(Number.isFinite) ? 'quantitative' : 'categorical'; }
function renderCountyDetails(payload) {
  const facts = $('#county-facts');
  if (!facts) return;
  const county = payload?.county || payload?.meta || {};
  const historical = payload?.historical_evidence || {};
  const current = payload?.current_availability || {};
  const selection = payload?.selection_asof;
  const matched = payload?.matched_policy || {}; const alternatives = payload?.alternatives || [];
  facts.replaceChildren();
  const table = document.createElement('table'); table.className = 'metric-table';
  const body = document.createElement('tbody');
  [
    ['County / FIPS', county.name ? `${county.name}, ${county.state || ''} · ${county.fips || scenario.fips}` : scenario.fips],
    ['Historical evidence', display(historical)],
    ['Current availability', display(current)],
    ['Selected station as of', selection?.station_name || selection?.station_id || 'Unavailable'],
    ['Matched hedge effectiveness', matched.metric?.value ?? 'Unavailable'],
    ['Metric definition', matched.metric?.definition ?? 'Unavailable'],
    ['Nearest-station effectiveness', matched.nearest_he ?? 'Unavailable'],
    ['Matched residual RMSE (degree days; larger is worse)', matched.residual_rmse_degree_days ?? 'Unavailable'],
    ['Effectiveness difference', matched.delta_he ?? 'Unavailable'],
    ['Matched interval', matched.interval?.low == null ? 'Unavailable' : `${matched.interval.low} to ${matched.interval.high} (${matched.interval.method})`],
    ['Matched policy support', matched.n_common == null ? matched.reason_code || 'Unavailable' : `${matched.n_common} common seasons: ${(matched.common_seasons || []).join(', ')}`],
    ['Current decision time', selection?.decision_time || selection?.valuation_date || 'Unavailable'],
    ['Observation cutoff / source', selection?.observation_cutoff ? `${selection.observation_cutoff} · ${selection.score_tape_id || 'frozen score tape'}` : 'Unavailable'],
  ].forEach(([label, value]) => { const row = document.createElement('tr'); const header = document.createElement('th'); header.scope = 'row'; header.textContent = label; const cell = document.createElement('td'); cell.textContent = value; row.append(header, cell); body.append(row); });
  table.append(body); facts.append(table);
  if (Array.isArray(alternatives) && alternatives.length) {
    const alternativeHeading = document.createElement('h3'); alternativeHeading.textContent = 'Station alternatives'; facts.append(alternativeHeading);
    const alternativeTable = document.createElement('table'); alternativeTable.className = 'metric-table';
    const head = document.createElement('thead'); const heading = document.createElement('tr'); ['Station', 'Distance km', 'Historical HE', 'Support', 'Evidence tier'].forEach((label) => { const cell = document.createElement('th'); cell.textContent = label; heading.append(cell); }); head.append(heading);
    const rows = document.createElement('tbody'); alternatives.forEach((item) => { const row = document.createElement('tr'); [item.station_name || item.station_id, item.distance_km, item.historical_he, item.n_test, item.metric_definition || item.status || 'Unavailable'].forEach((value) => { const cell = document.createElement('td'); cell.textContent = display(value); row.append(cell); }); rows.append(row); }); alternativeTable.append(head, rows); facts.append(alternativeTable);
  }
}
function renderSummaryTable(rows, layer, kind) {
  let panel = $('#drawer-summary-table');
  if (!panel) { panel = document.createElement('section'); panel.id = 'drawer-summary-table'; panel.setAttribute('aria-label', 'Searchable county results table'); $('.result-panel')?.append(panel); }
  panel.replaceChildren(); const input = document.createElement('input'); input.type = 'search'; input.placeholder = 'Filter county name, state, or FIPS'; input.setAttribute('aria-label', 'Filter county summary table'); const table = document.createElement('table'); table.className = 'metric-table'; const head = document.createElement('thead'); const header = document.createElement('tr'); ['County / FIPS', layer, 'Availability'].forEach((label) => { const cell = document.createElement('th'); cell.textContent = label; header.append(cell); }); head.append(header); const body = document.createElement('tbody'); const draw = () => { const query = input.value.trim().toLowerCase(); body.replaceChildren(); rows.filter((row) => { const county = counties.find((item) => item.fips === String(row.fips).padStart(5, '0')); return !query || `${county?.name || ''} ${county?.state || ''} ${row.fips}`.toLowerCase().includes(query); }).slice(0, 250).forEach((row) => { const value = row.layers?.[layer]; const county = counties.find((item) => item.fips === String(row.fips).padStart(5, '0')); const record = document.createElement('tr'); const name = county ? `${county.name}, ${county.state} · ${row.fips}` : row.fips; [name, display(layerScalar(value)), kind === 'quantitative' ? (value?.reason_code || value?.status || 'Available') : display(value?.label || value?.status || value?.reason_code || value)].forEach((entry) => { const cell = document.createElement('td'); cell.textContent = entry; record.append(cell); }); body.append(record); }); }; input.addEventListener('input', draw); draw(); table.append(head, body); panel.append(input, table);
}
function showCounty(state) {
  const name = $('#county-name'); const status = $('#county-load-status');
  if (!name || !status) return;
  if (state.phase === 'loading') { status.textContent = `Loading ${state.committedFips}. Results still visible for ${state.visibleFips}.`; return; }
  if (state.phase === 'error') { status.textContent = `Could not load ${state.committedFips}. ${state.error.message} Retry or choose another county.`; return; }
  name.textContent = countyTitle(state.payload?.payload, state.committedFips);
  status.textContent = `Showing ${state.committedFips} from release ${scenario.releaseId}.`;
  renderCountyDetails(state.payload?.payload);
}
async function initializeExplore() {
  const status = $('#county-search-status');
  try {
    const registry = bootstrap.objects.find((object) => object.result_type === 'county_registry');
    counties = bootstrap.county_registry || registry?.payload?.counties || [];
  }
  catch (error) { status.textContent = `County search is unavailable. ${error.message}`; return; }
  selection = createSelectionController({
    initialFips: scenario.fips,
    loadCounty: (fips, signal) => client.object(bootstrap, `county:${fips}:${scenario.indexId}`, signal),
    onChange: showCounty,
  });
  mountCountyCombobox({ input: $('#county-search'), listbox: $('#county-options'), status, counties, selectedFips: scenario.fips,
    onCommit: async (fips) => { setScenario({ fips }); await selection.commit(fips); },
  });
  $('#retry-county')?.addEventListener('click', () => selection.commit(selection.committedFips));
  await selection.commit(scenario.fips);
  const map = $('#atlas-map');
  if (map) {
    try {
      const summary = await loadObject(`summary:${scenario.indexId}`);
      const rows = summary.payload?.rows || summary.payload?.counties || [];
      const layers = [...new Set(rows.flatMap((row) => Object.keys(row.layers || {})))];
      const controls = document.createElement('fieldset'); controls.innerHTML = '<legend>Map layer</legend>'; const legend = document.createElement('p'); legend.className = 'availability';
      let activeLayer = layers[0] || null;
      const renderLayer = () => { const kind = layerKind(rows, activeLayer); const values = rows.map((row) => layerScalar(row.layers?.[activeLayer])).filter((value) => value != null); legend.textContent = kind === 'quantitative' ? 'Quantitative legend: blue positive, red negative, pale zero, gray missing.' : `Categorical legend: ${[...new Set(values.map(String))].slice(0, 8).join(', ') || 'no available categories'}; gray missing.`; renderSummaryTable(rows, activeLayer, kind); return renderAtlasMap(map, { topologyUrl: 'assets/vendor/counties-albers-10m.json', summary: rows.map((row) => ({ ...row, metric_value: layerScalar(row.layers?.[activeLayer]) })), layerKind: kind, selectedFips: selection.committedFips, onSelect: async (fips) => { setScenario({ fips }); await selection.commit(fips); } }); };
      layers.forEach((layer) => { const button = document.createElement('button'); button.type = 'button'; button.textContent = layer; button.setAttribute('aria-pressed', String(layer === activeLayer)); button.addEventListener('click', () => { activeLayer = layer; [...controls.querySelectorAll('button')].forEach((item) => item.setAttribute('aria-pressed', String(item.textContent === layer))); renderLayer().catch((error) => { $('#map-status').textContent = error.message; }); }); controls.append(button); });
      if (layers.length) $('.control-panel')?.append(controls, legend);
      await renderLayer();
    }
    catch (error) { $('#map-status').textContent = error.message; }
  }
}
function bindSharedControls() {
  $('#copy-scenario')?.addEventListener('click', async () => {
    await navigator.clipboard?.writeText(new URL(location.href).toString());
    $('#scenario-status').textContent = 'Share link copied.';
  });
  $('#reset-scenario')?.addEventListener('click', () => { scenario = normalizeScenario(); replaceUrl(scenario); location.reload(); });
  $('#strike')?.addEventListener('change', (event) => setScenario({ strike: event.target.value }));
  $('#index')?.addEventListener('change', (event) => { setScenario({ indexId: event.target.value }); location.reload(); });
  window.addEventListener('popstate', () => { const decoded = decodeScenario(); if (decoded.scenario) { scenario = decoded.scenario; location.reload(); } });
}
async function start() {
  const decoded = decodeScenario();
  if (decoded.error) { $('#scenario-status').textContent = decoded.error; return; }
  scenario = decoded.scenario;
  if (!scenario.releaseId) {
    const pointer = await client.current();
    if (!pointer?.release_id) throw new Error('The current release pointer has no release identity.');
    scenario = normalizeScenario({ ...scenario, releaseId: pointer.release_id });
    replaceUrl(scenario, 'replaceState');
  }
  bootstrap = await client.bootstrap(scenario.releaseId);
  if (bootstrap.capabilities?.scope === 'artificial_fixture') $('#scenario-status').textContent = 'Artificial numerical fixture for browser and solver checks; not empirical weather evidence.';
  populateIndexOptions();
  if (decoded.legacy) $('#scenario-status').textContent = 'This is a V1 hash link. Open the archived V1 release for its original result.';
  renderScenarioSummary(); bindSharedControls();
  if (document.body.dataset.page === 'explore') await initializeExplore();
  if (document.body.dataset.page === 'compare') mountCompare({ bootstrap, counties: bootstrap.county_registry || bootstrap.objects.find((item) => item.result_type === 'county_registry')?.payload?.counties || [], scenario, loadObject, setScenario });
  if (document.body.dataset.page === 'contract') await mountContract({ scenario, loadObject, setScenario });
  if (document.body.dataset.page === 'portfolio') mountPortfolio({ bootstrap, scenario, loadObject });
  if (document.body.dataset.page === 'research') mountResearch({ bootstrap, loadObject, scenario, setScenario });
}
start().catch((error) => { const status = $('#scenario-status'); if (status) status.textContent = `The workbench could not start. ${error.message}`; });
