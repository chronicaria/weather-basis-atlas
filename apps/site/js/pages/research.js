import { keyValueTable, node, replacePanel } from './render.js';

const title = (key) => ({ glossary: 'Glossary', method: 'Methods and registered results', source_support: 'Source support', holdout: 'Consumed holdout ledger', limitations: 'Limits of this release', performance: 'Measured performance', validation: 'Validation topology', r01: 'R01: prior best versus nearest', r02: 'R02: sparse basket', r03: 'R03: joint book', r04: 'R04: marginal and dependence', r05: 'R05: irreducible basis map', nebraska: 'Nebraska case', next_station: 'Next-station pilot' }[key] || key.replaceAll('_', ' '));
const text = (value) => value == null ? 'Unavailable' : typeof value === 'object' ? value.reason_code || value.status || 'Available' : String(value);
function table(headers, rows) { const out = node('table', undefined, { class: 'metric-table' }); const head = node('thead'); const header = node('tr'); headers.forEach((label) => header.append(node('th', label))); head.append(header); const body = node('tbody'); rows.forEach((values) => { const row = node('tr'); values.forEach((value) => row.append(node('td', text(value)))); body.append(row); }); out.append(head, body); return out; }
const atomic = (value) => value === null || typeof value !== 'object';
function structured(label, value, depth = 0) {
  if (atomic(value)) return keyValueTable([[label, value]]);
  if (Array.isArray(value) && value.every(atomic)) return table(['Item', 'Value'], value.map((item, index) => [index + 1, item]));
  const section = node('section', undefined, { class: 'research-data' });
  if (label) section.append(node(depth > 1 ? 'h5' : 'h4', title(label)));
  if (Array.isArray(value)) {
    value.forEach((item, index) => { const detail = node('details'); detail.append(node('summary', `${title(label || 'row')} ${index + 1}`), structured('', item, depth + 1)); section.append(detail); });
    return section;
  }
  const entries = Object.entries(value); const fields = entries.filter(([, item]) => atomic(item));
  if (fields.length) section.append(keyValueTable(fields));
  entries.filter(([, item]) => !atomic(item)).forEach(([name, item]) => { const detail = node('details'); detail.append(node('summary', title(name)), structured('', item, depth + 1)); section.append(detail); });
  return section;
}
function renderEvidence(key, record) {
  const payload = record.payload || {}; const section = node('section', undefined, { class: 'research-record', id: `research-${key}` }); section.append(node('h3', title(key)), node('p', record.status === 'available' ? 'Available evidence.' : `Evidence status: ${record.status}. ${record.reason_code || ''}`));
  if (key === 'glossary') section.append(table(['Term', 'Definition'], (payload.terms || []).map((item) => [item.term, item.definition])), node('p', payload.canonical_index));
  else if (key === 'source_support') section.append(table(['Support', 'Variable', 'Location', 'Coverage', 'Historical availability', 'Limit'], (payload.sources || []).map((item) => [item.support_id, item.variable, item.location_type, `${item.coverage_start} to ${item.coverage_end}`, item.historical_availability, item.unsupported_reason])));
  else if (key === 'holdout') section.append(table(['Period', 'Status', 'Interpretation'], (payload.access_ledger || []).map((item) => [item.period, item.status, item.interpretation])), node('p', payload.scoreability));
  else if (key === 'limitations') { const list = node('ul'); (payload.items || []).forEach((item) => list.append(node('li', item))); section.append(list); }
  else if (key === 'performance') section.append(keyValueTable([['Producer', payload.r04_producer], ['Peak RSS', payload.peak_rss_bytes], ['Interpretation', payload.meaning]]), table(['Origin', 'Columns', 'Seconds', 'Peak RSS', 'Scoreability'], (payload.origins || []).map((item) => [item.origin, item.columns, item.runtime_seconds, item.peak_rss_bytes, item.scoreability])));
  else if (key === 'validation') section.append(keyValueTable(Object.entries(payload.topology || {})), table(['Origin', 'Fit cutoff', 'Scoreability', 'Common-year CRPS', 'R2j CRPS', 'Unavailable reason'], (payload.r04_origins || []).map((item) => [item.origin, item.fit_cutoff, item.scoreability, item.common_year_mean_crps, item.r2j_mean_crps, item.unavailable_reason])), node('p', payload.uncertainty));
  else if (key === 'method') Object.entries(payload).forEach(([name, item]) => section.append(node('h4', title(name)), keyValueTable(Object.entries(item).map(([label, value]) => [label, Array.isArray(value) ? value.join(', ') : value]))));
  else {
    const experiment = payload.registered_experiment || payload.report || payload.case || payload;
    const results = experiment.results || payload.results || [];
    const headline = experiment.disposition || payload.interpretation || payload.disposition || 'Registered result; inspect the reported values below.';
    section.append(keyValueTable([['Experiment / case', experiment.experiment || experiment.experiment_id || experiment.case || key], ['Scope', payload.limitations || payload.scope || experiment.scope], ['Protocol', experiment.protocol_id || record.analysis_id], ['Disposition / interpretation', headline]]));
    if (key === 'next_station') section.append(node('p', 'This case panel preserves the preregistered counterfactual, observed coverage, uncertainty, costs, and final disposition from the frozen pilot.'));
    section.append(structured('Reported evidence', payload));
  }
  section.append(node('p', `Result ${record.object_id} · analysis ${record.analysis_id} · source ${record.evidence_reference}`)); return section;
}

export function mountResearch({ bootstrap, loadObject, scenario, setScenario }) {
  const panel = replacePanel('.lab-panel', [node('h2', 'Evidence library')]); const records = bootstrap.objects.filter((object) => ['research', 'research_evidence'].includes(object.result_type));
  if (!records.length) { panel.append(node('p', 'No research projections are published for this release.')); return; }
  const nav = node('nav', undefined, { class: 'route-list', 'aria-label': 'Research records' }); const detail = node('div', undefined, { 'aria-live': 'polite' }); const buttons = new Map();
  let selected = scenario.researchRecord;
  records.forEach((reference) => { const key = reference.object_key || reference.object_id; const button = node('button', title(key.replace(/^research:/, '')), { type: 'button' }); button.addEventListener('click', async () => { if (selected !== key) { selected = key; setScenario({ researchRecord: key }); } detail.replaceChildren(node('p', 'Loading frozen evidence…')); try { const record = await loadObject(key); detail.replaceChildren(renderEvidence(key.replace(/^research:/, ''), record)); } catch (error) { detail.replaceChildren(node('p', `Evidence unavailable: ${error.message}`)); } }); buttons.set(key, button); nav.append(button); });
  panel.append(nav, detail); const requested = scenario.researchRecord;
  if (requested && !buttons.has(requested)) { detail.append(node('p', `Evidence unavailable: this release does not contain ${requested}. Choose a listed research record.`)); return; }
  (buttons.get(requested) || nav.querySelector('button'))?.click();
}
