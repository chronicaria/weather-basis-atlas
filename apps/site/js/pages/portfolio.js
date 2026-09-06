import { node, replacePanel } from './render.js';
import { holdingsTemplate, parseHoldingsCsv } from '../controls/holdings-csv.js';
import { compileHoldingsProblem } from '../data/holdings-problem.js';
import {
  NA, button, countyLabel, dataTable, dateRange, envelopeProvenance, field, humanize, kvTable, monthName, num, pairLabel, pct, provenanceBlock, rangeText, shortId, stationCity, stationId, stationLabel, statusText, tile, tiles, usd,
} from './format.js';

/* ------------------------------------------------------------------------
 * Calculation, identity and export helpers.
 * These produce the accepted decision record, its hash, the memo and the
 * CSV/JSON exports. They are byte-for-byte the release contract: do not edit.
 * --------------------------------------------------------------------- */

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
  if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('Decision records cannot contain non-finite numbers.');
  return JSON.stringify(value);
}

function jsonSafe(value) {
  if (Array.isArray(value)) return value.map(jsonSafe);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).filter(([, item]) => item !== undefined).map(([key, item]) => [key, jsonSafe(item)]));
  return typeof value === 'number' && !Number.isFinite(value) ? null : value;
}

async function decisionIdentity(record) {
  const unsigned = { ...record }; delete unsigned.decision_id;
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonicalJson(unsigned)));
  return `decision:${[...new Uint8Array(digest)].map((part) => part.toString(16).padStart(2, '0')).join('')}`;
}

function download(value, filename, type = 'application/json') {
  const link = node('a'); const url = URL.createObjectURL(new Blob([value], { type }));
  link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 0);
}

function csv(rows) {
  const cell = (value) => `"${String(value ?? '').replaceAll('"', '""')}"`;
  return rows.map((row) => row.map(cell).join(',')).join('\n') + '\n';
}

function constraintSummary(residuals = {}) {
  const entries = Object.entries(residuals).filter(([, value]) => value != null && Number.isFinite(Number(value)));
  const binding = entries.filter(([, value]) => Math.abs(Number(value)) < 1e-7).map(([key]) => key);
  return { entries, binding };
}

function adverseRows(problem, output) {
  return (output.residual_loss || []).map((loss, index) => ({ scenario_id: problem.scenario_ids?.[index], residual_loss: loss }))
    .filter((row) => row.scenario_id && Number.isFinite(Number(row.residual_loss)))
    .sort((left, right) => Number(right.residual_loss) - Number(left.residual_loss)).slice(0, 3);
}

function replayProblem(problem) {
  const replay = jsonSafe(problem);
  if (Array.isArray(problem.upper_bounds) && problem.upper_bounds.every((value) => value === Infinity)) delete replay.upper_bounds;
  return replay;
}

function decisionMemo(record) {
  const risk = record.result.risk || {}; const baseline = record.baseline || {}; const baselineRisk = baseline.risk || {};
  const request = record.request || {}; const problem = request.problem || {}; const book = request.book || {}; const constraints = constraintSummary(record.result.constraint_residuals);
  const adverse = (record.adverse_scenarios || []).map((row) => `- ${row.scenario_id}: residual loss ${row.residual_loss}`).join('\n') || '- Unavailable';
  const holdings = (request.holdings || book.holdings || []).map((row) => `- ${row.row_id || 'row'}: ${row.kind || row.loss_kind || 'holding'} on ${row.entity_id || 'unidentified'}`).join('\n') || '- None';
  const contracts = Object.entries(book.candidate_contracts || {}).map(([id, value]) => `- ${id}: ${JSON.stringify(value)}`).join('\n') || '- No candidate contracts recorded';
  return `# Portfolio decision memo\n\n## Question\n\n${record.question}\n\n## Identity and replay boundary\n\nDecision: \`${record.decision_id}\`\n\nRelease: \`${record.release_id || request.release_id || 'Unavailable'}\` · Scenario set: \`${record.scenario_set_id}\`\n\nScenario sample: ${problem.scenario_ids?.length ?? 'Unavailable'} paths; units ${problem.units || record.result.units || 'USD'}; lots ${request.lots ? 'enforced' : 'continuous'}.\n\n## Holdings and contracts\n\n${holdings}\n\nCandidate contracts:\n${contracts}\n\n## Baseline versus accepted decision\n\n| Measure | Zero-position baseline | Accepted decision |\n| --- | ---: | ---: |\n| Expected shortfall | ${baselineRisk.expected_shortfall ?? 'Unavailable'} | ${risk.expected_shortfall ?? 'Unavailable'} |\n| Variance | ${baselineRisk.variance ?? 'Unavailable'} | ${risk.variance ?? 'Unavailable'} |\n| Deterministic cost | ${baseline.deterministic_cost ?? 'Unavailable'} | ${record.result.deterministic_cost ?? 'Unavailable'} |\n\nPositions: \`${JSON.stringify(record.result.positions)}\`\n\n## Constraints and feasibility\n\nObjective: ${request.objective || record.result.objective || 'evaluation'}; ES target: ${request.es_target ?? 'Unavailable'}; cash budget: ${request.cash_budget ?? problem.cash_budget ?? 'Unavailable'}.\n\nBinding constraints: ${constraints.binding.join(', ') || 'none reported'}.\n\nConstraint residuals: \`${JSON.stringify(record.result.constraint_residuals || {})}\`\n\nStatus: ${record.result.status}; reason: ${record.result.reason_code || 'none'}.\n\n## Adverse sampled paths\n\n${adverse}\n\n## Assumptions and provenance\n\nCost assumptions: \`${JSON.stringify(book.cost_policy || { cost_multiplier: request.cost_multiplier ?? 1 })}\`\n\nSources: ${(record.source_artifact_ids || []).join(', ') || 'No public source IDs were supplied.'}\n\nModel specifications: ${(record.model_spec_ids || []).join(', ') || 'None recorded.'}\n\nObject identities: ${(record.object_ids || []).join(', ') || 'None recorded.'}\n\n${record.uncertainty}\n\n## Reproduction\n\nSave the exported JSON as \`decision.json\`, then run:\n\n\`uv run python scripts/replay_portfolio_decision.py decision.json\`\n\nTo inspect the same accepted record in the browser, use Portfolio Lab → Import local book, accepted decision, or CSV, choose the JSON file, and confirm the displayed decision identity before exporting again.\n`;
}

async function portfolioKernel() {
  if (window.WbaPortfolio) return window.WbaPortfolio;
  await new Promise((resolve, reject) => { const script = node('script'); script.src = 'js/kernels/portfolio.js'; script.onload = resolve; script.onerror = () => reject(new Error('Portfolio kernel could not load.')); document.head.append(script); });
  return window.WbaPortfolio;
}

function workerRequest(worker, request) {
  return new Promise((resolve, reject) => {
    const listener = ({ data }) => { if (data.request_id !== request.request_id || data.input_hash !== request.input_hash) return; worker.removeEventListener('message', listener); if (data.type === 'error') reject(new Error(data.payload?.message || data.payload?.reason_code || 'Worker calculation failed.')); else resolve(data.payload); };
    worker.addEventListener('message', listener); worker.postMessage(request);
  });
}

/* ------------------------------------------------------------------------
 * Plain-language presentation helpers (display only).
 * --------------------------------------------------------------------- */

const ES_MEANING = 'average loss in the worst 10% of simulated seasons';
const OBJECTIVES = [
  ['es', 'Minimise expected shortfall (ES90)'],
  ['min_cost_es', 'Minimise cost for an ES90 target'],
  ['variance', 'Minimise variance of the net loss'],
  ['mse', 'Match losses as closely as possible (mean squared error)'],
];
const OBJECTIVE_LABEL = Object.fromEntries(OBJECTIVES);
const STATUS_WORDS = {
  optimal: 'Optimal solution found', infeasible: 'No feasible hedge under these rules', numerical_failure: 'The solver could not finish reliably',
  available: 'Current positions evaluated', cancelled: 'Calculation cancelled', disposed: 'Solver reset', ready: 'Ready',
};
const CONSTRAINT_WORDS = {
  lower_bounds: 'positions cannot be negative', upper_bounds: 'the cap on each position', max_active: 'the limit on how many contracts may be used', max_stations: 'the maximum number of stations',
  cash_budget: 'the cash budget', es_target: 'the ES90 target', turnover_limit: 'the turnover limit', station_limits: 'the per-station limits', region_limits: 'the per-region limits',
};
const HOLDING_KINDS = [
  ['heating_shortfall', 'Heating exposure'],
  ['cooling_overrun', 'Cooling exposure'],
  ['claim', 'Claim you are liable for'],
  ['hedge', 'Hedge you already hold'],
];
/** Solver reason codes under an unsolved result: a plain sub-line, or none where the code adds nothing. */
const REASON_SUBS = {
  solver_status: null,
  worker_error: 'The solver stopped before it finished',
  constraint_violation: 'The answer broke one of the rules, so it was not accepted',
};
const PAYOFF_WORDS = { put: 'Put', call: 'Call', put_spread: 'Put spread', call_spread: 'Call spread', capped_put: 'Capped put', capped_call: 'Capped call', collar: 'Collar' };
const BOOK_TITLES = { 'multi-location-cooling': 'Multi-location cooling book', 'regional-heating': 'Regional heating book', 'underwriter-capped-claim': 'Underwriter capped-claim book' };
const isFinite_ = (value) => value !== null && value !== '' && value !== undefined && Number.isFinite(Number(value));

function objectiveLabel(value) { return value ? OBJECTIVE_LABEL[value] || humanize(value) : 'Evaluation of the current positions'; }
function statusWord(value) { return value == null ? NA : STATUS_WORDS[value] || statusText(value); }
function constraintWord(key) { return CONSTRAINT_WORDS[key] || humanize(key); }
function joinList(items) { const list = items.filter(Boolean); if (list.length <= 1) return list.join(''); return `${list.slice(0, -1).join(', ')} and ${list.at(-1)}`; }
/** "9.73 contracts", "6 contracts"; a solver's negative zero is shown as zero. */
function positionText(position) {
  if (!isFinite_(position)) return NA;
  const raw = Math.abs(Number(position)) < 1e-9 ? 0 : Number(position);
  const value = Math.abs(raw - Math.round(raw)) < 1e-9 ? Math.round(raw) : raw;
  return `${num(value, Number.isInteger(value) ? 0 : 2)} contract${Math.abs(value) === 1 ? '' : 's'}`;
}
/** Numbers typed back into the holdings table arrive with separators; read them as written. */
function readNumber(text) { const cleaned = String(text ?? '').replace(/[,\s$]/g, '').replace(/−/g, '-'); return cleaned === '' ? NaN : Number(cleaned); }
/** Cell text for an editable number: formatted for reading, still parseable when edited. */
function cellNumber(value, digits) { if (!isFinite_(value)) return value ?? ''; const number = Number(value); return num(number, digits ?? (Number.isInteger(number) ? 0 : 2)); }
/** "39% lower" / "12% higher" / "—" against the unhedged reference. */
function changeWords(reference, value) {
  if (!isFinite_(reference) || !isFinite_(value) || Number(reference) <= 0) return '—';
  const reduction = 1 - Number(value) / Number(reference);
  if (Math.abs(reduction) < 0.005) return '—';
  return reduction > 0 ? `${pct(reduction, 0)} lower` : `${pct(-reduction, 0)} higher`;
}
/** ES90 change relative to the zero-position baseline, as a phrase for a tile. */
function esChange(baselineEs, hedgedEs) {
  if (!isFinite_(baselineEs) || !isFinite_(hedgedEs) || Number(baselineEs) <= 0) return null;
  const reduction = 1 - Number(hedgedEs) / Number(baselineEs);
  if (reduction > 0.0005) return { reduction, text: `${pct(reduction, 0)} lower than with no hedge` };
  if (reduction < -0.0005) return { reduction, text: `${pct(-reduction, 0)} higher than with no hedge` };
  return { reduction, text: 'no change from the unhedged book' };
}

/** Calculation errors (kernel, compiler, worker, loader) → one plain sentence for the status line. */
const ERROR_WORDS = [
  [/^(.+?) entity lacks scenario support$/, (m) => `Row ${m[1]} refers to a location and index with no simulated seasons in this release. Use a county FIPS code and month such as 31109:HDD-01, or a listed station code as in the CSV template.`],
  [/does not contain county_scenarios:(\d{5})/, (m) => `No simulated seasons are published for county ${m[1]} in this release, so it cannot be part of a book.`],
  [/does not contain station_scenarios/, () => 'The station scenarios for this release could not be found, so nothing can be calculated.'],
  [/^(.+?) needs heating_shortfall, cooling_overrun, or contract_payoff/, (m) => `Row ${m[1]} has a kind of holding the lab cannot calculate on its own. Heating and cooling exposures work anywhere; a claim has to come from Contract Lab so that it carries its payoff terms.`],
  [/^Explicit hedge (.+?) needs entity_id and payoff_spec/, (m) => `Hedge row ${m[1]} needs a station index, a payoff and a strike.`],
  [/Explicit hedge (.+?) unit cost/, (m) => `Hedge row ${m[1]} needs a numeric unit cost.`],
  [/Explicit hedge candidate IDs must be unique/, () => 'Each hedge row needs its own hedge candidate name; two rows share one.'],
  [/Selected candidate IDs must be an ordered subset/, () => 'The ticked hedge candidates no longer match the hedge rows. Re-tick them and run again.'],
  [/No hedge candidates are declared/, () => 'There are no hedge candidates to choose from. Add hedge rows to the holdings, import the CSV template, or start from an example book.'],
  [/Published candidate .* has no explicit frozen contract|lacks station entity or payoff kind/, () => 'One of the ticked hedge candidates has no published contract, so it cannot be priced.'],
  [/Candidate .* (multiplier|strike|frozen unit cost) must be finite/, () => 'A published hedge candidate is missing its price or terms, so it cannot be used.'],
  [/exposure requires finite amount and budget/, () => 'Every exposure row needs a numeric Amount and Budget.'],
  [/unsupported payoff kind (\S+)/, (m) => `The payoff "${m[1]}" is not supported. Use put, call, put_spread, call_spread or collar.`],
  [/option payoff requires finite strike/, () => 'Every hedge row needs a numeric strike.'],
  [/invalid payoff multiplier/, () => 'Every hedge row needs a multiplier of zero or more dollars per degree day.'],
  [/requires (high_strike|low_strike|call_strike)/, () => 'A spread or collar needs its second strike on the correct side of the first.'],
  [/claim cap must be finite|option cap must be finite/, () => 'A cap must be a number of dollars, zero or more.'],
  [/needs a closed payoff structure|contract_payoff requires/, () => 'A claim from Contract Lab needs its complete payoff description; append it again from Contract Lab.'],
  [/at most six counties|more than six/, () => 'The browser solver supports at most six counties in one book.'],
  [/browser_limit_exceeded/, () => 'This book is larger than the browser solver allows (6 counties, 24 exposures, 39 candidates, 2,000 seasons). Use the offline workflow described in the research notes.'],
  [/min_cost_es requires|Minimum-cost ES requires/, () => 'Minimising cost needs an ES90 target in step 3.'],
  [/unsupported_cardinality_qp/, () => 'The variance and mean-squared-error objectives cannot be combined with a maximum number of stations in the browser. Clear the maximum, or choose an ES90 objective.'],
  [/cardinality constraints require finite upper_bounds/, () => 'A maximum number of stations needs a position cap on every candidate, which this book does not set.'],
  [/long-only candidates|short positions require allow_short/, () => 'The browser solver only takes long positions; a book that allows short positions must be solved offline.'],
  [/scenario coordinates differ|do not share the exact scenario coordinates|repeat an entity ID/, () => 'The simulated seasons for these counties and stations do not line up, so the book cannot be calculated in this release.'],
  [/not a complete aligned ScenarioMatrix|does not match its declared shape|identity does not match its matrix parent|Integrity check failed|not valid JSON/, () => 'The simulated-season data for this book could not be verified, so nothing was calculated.'],
  [/weights must be|stress scenarios without weights/, () => 'The simulated seasons for this book carry no usable probability weights.'],
  [/input_hash does not match/, () => 'The problem changed while the solver was running. Run the calculation again.'],
  [/worker must be initialized|Worker calculation failed|kernel could not load|Failed to fetch|NetworkError|importScripts|highs/i, () => 'The solver could not start in this browser. Reload the page and try again.'],
  [/non-finite numbers/, () => 'The result contains values that cannot be recorded, so no decision was saved.'],
  [/Could not load/, () => 'Part of the release data could not be loaded. Check the connection and try again.'],
];
function friendlyError(message) {
  const text = String(message ?? '').trim();
  for (const [pattern, words] of ERROR_WORDS) { const match = pattern.exec(text); if (match) return words(match); }
  const plain = text.replace(/^[a-z_]+:\s*/i, '').replaceAll('_', ' ').replace(/^\w/, (c) => c.toUpperCase());
  return plain ? (/[.!?]$/.test(plain) ? plain : `${plain}.`) : 'The calculation could not be completed.';
}
function entityParts(entityId) { const text = String(entityId ?? '').replace(/^(county|station):/, ''); const [head, pair] = text.split(':'); return { head: head || '', pair: pair || '' }; }

function placeLabel(entityId, countyFor) {
  const { head } = entityParts(entityId);
  if (stationId(head)) return stationLabel(head, { withName: false });
  if (/^\d{5}$/.test(head)) { const county = countyFor?.(head); return county ? countyLabel(county, head) : `County ${head}`; }
  return head || NA;
}

/** "Put on January heating degree days, strike 1,205, $20 per degree day". */
function contractSentence(contract = {}) {
  const spec = contract.payoff_spec || {};
  const entity = contract.station_entity_id || contract.entity_id; const { pair } = entityParts(entity);
  const payoff = contract.payoff || contract.payoff_kind || spec.kind || contract.kind;
  const strike = contract.strike ?? spec.strike; const multiplier = contract.multiplier_usd_per_degree_day ?? contract.multiplier ?? spec.multiplier;
  const bits = [`${payoff ? PAYOFF_WORDS[payoff] || humanize(payoff) : 'Contract'}${pair ? ` on ${pairLabel(pair)}` : ''}`];
  if (isFinite_(strike)) bits.push(`strike ${num(strike, 0)}`);
  if (isFinite_(multiplier)) bits.push(`${usd(multiplier)} per degree day`);
  return bits.join(', ');
}

/** Turn a simulated-season identifier into a readable label; the raw id goes to provenance. */
function seasonLabel(scenarioId) {
  const text = String(scenarioId ?? '');
  const observed = /historical-observed-(\d{4})/.exec(text); if (observed) return `Observed season ${observed[1]}`;
  const stress = /^stress-(.+)-(\d{4})$/.exec(text); if (stress) return `Stressed ${stress[2]}`;
  const numbered = /-(\d+)$/.exec(text); if (numbered) return `Simulated season ${Number(numbered[1])}`;
  return text || NA;
}

/** "Worst season (no. 1617)", "2nd worst (no. 1649)" for the ranked adverse table. */
const RANK_WORDS = ['Worst season', '2nd worst', '3rd worst', '4th worst', '5th worst'];
function adverseLabel(scenarioId, rank) {
  const label = seasonLabel(scenarioId); const simulated = /^Simulated season (\d+)$/.exec(label);
  return `${RANK_WORDS[rank] || `No. ${rank + 1} worst`} (${simulated ? `no. ${simulated[1]}` : label})`;
}

/** Scenario Room names from their keys: "stress:uniform_warm_3f" → "Uniform +3 °F warmer". */
function roomName(key, payload) {
  const inner = String(key ?? '').replace(/^scenario_room:/, '');
  if (inner === 'historical') {
    const years = (payload?.source_windows || []).map((item) => item.source_year).filter(Boolean);
    return years.length ? `Observed seasons ${joinList(years.map(String))}` : 'Observed seasons';
  }
  const stress = /^stress:(.+?)_(warm|cold)_(\d+)f$/.exec(inner);
  if (stress) return `${humanize(stress[1])} ${stress[2] === 'warm' ? '+' : '−'}${stress[3]} °F ${stress[2] === 'warm' ? 'warmer' : 'colder'}`;
  return humanize(inner);
}

/** "+3F uniform temperature shift" → "Every observed day made 3 °F warmer, everywhere in the book." */
function constructionWords(construction) {
  const text = String(construction ?? '').trim();
  if (!text) return null;
  const shift = /^([+-])(\d+(?:\.\d+)?)\s*F\b\s*(.*)$/.exec(text);
  if (!shift) return /[.!?]$/.test(text) ? text : `${text}.`;
  const rest = shift[3].trim().replace(/^uniform temperature shift$/i, 'everywhere in the book').replace(/^only for /i, 'only at ');
  const tail = rest ? `, ${/^only at /.test(rest) ? 'but ' : ''}${rest}` : '';
  return `Every observed day made ${shift[2]} °F ${shift[1] === '+' ? 'warmer' : 'colder'}${tail}.`;
}
/** What the room's weather actually is, without repeating the room's own name. */
function weatherWords(payload) {
  return constructionWords(payload?.construction) || 'Daily temperatures exactly as they were recorded in those seasons, with no shift applied.';
}
/** A season the room could not build, and why, in plain words. */
const OMITTED_REASON_WORDS = { missing_daily_temperature_support: 'no complete daily temperature record' };
function omittedSeasonWords(item = {}) {
  const season = item.source_year || seasonLabel(item.scenario_id);
  const reason = OMITTED_REASON_WORDS[item.reason_code] || statusText(item.reason_code || 'unavailable').toLowerCase().replace(/\.$/, '');
  const where = item.missing_location_ids?.length ? ` at ${joinList(item.missing_location_ids.map((id) => stationLabel(id, { withName: false })))}` : '';
  return `${season}: ${reason}${where} for that season.`;
}

/** Why a Scenario Room cashflow carries no risk measures, in plain words. */
function riskReasonWords(reason) {
  const text = String(reason ?? '').trim();
  if (/null weights|no probability/i.test(text)) return 'Not calculated: stress weather carries no probability weights, so ES90 cannot be worked out for it.';
  if (/descriptive only/i.test(text)) return 'Not calculated: observed seasons are shown as they happened, so no predictive ES90 is computed.';
  return text ? humanize(text) : 'Not calculated';
}

function bookTitle(key, book) { const id = String(book?.book_id || String(key).replace(/^book:/, '')).replace(/-v\d+$/, ''); return BOOK_TITLES[id] || `${humanize(id.replaceAll('-', ' '))} book`; }

/** One line derived from the holdings: what is exposed, where, and how many contracts are on offer. */
function bookDescription(book, countyFor, candidateCount) {
  const exposures = (book.holdings || []).filter((holding) => !holding.candidate_id);
  if (!exposures.length) return 'No exposures recorded.';
  const kinds = new Set(exposures.map((holding) => holding.loss_kind || holding.kind));
  const kindWord = kinds.has('heating_shortfall') && kinds.has('cooling_overrun') ? 'heating and cooling' : kinds.has('heating_shortfall') ? 'heating' : kinds.has('cooling_overrun') ? 'cooling' : '';
  const claims = exposures.filter((holding) => holding.kind === 'claim').length; const plain = exposures.length - claims;
  const months = [...new Set(exposures.map((holding) => monthName(entityParts(holding.entity_id).pair)).filter(Boolean))];
  const fipsList = [...new Set(exposures.map((holding) => entityParts(holding.entity_id).head))];
  const places = fipsList.map((fips) => countyFor?.(fips)?.name?.replace(/ County$/, '') || placeLabel(fips, countyFor));
  const states = [...new Set(fipsList.map((fips) => countyFor?.(fips)?.state).filter(Boolean))];
  const where = fipsList.every((fips) => /^\d{5}$/.test(fips)) ? `${joinList(places)} ${places.length > 1 ? 'counties' : 'county'}${states.length === 1 ? `, ${states[0]}` : ''}` : joinList(places);
  const what = [plain ? `${plain} ${kindWord} exposure${plain === 1 ? '' : 's'}` : '', claims ? `${claims} ${plain ? '' : `${kindWord} `}claim${claims === 1 ? '' : 's'}` : ''].filter(Boolean).join(' and ');
  return `${what}${months.length ? ` for ${joinList(months)}` : ''} in ${where}. ${candidateCount} station contract${candidateCount === 1 ? '' : 's'} to choose from.`;
}

/** A season-by-season spread in words: one figure when it never moves, a gain-to-loss
 *  sentence when the quantity can go either way. */
function distributionEntry(values, { loss = false } = {}) {
  const finite = (Array.isArray(values) ? values : []).map(Number).filter(Number.isFinite).sort((a, b) => a - b);
  if (!finite.length) return NA;
  const low = finite[0]; const high = finite.at(-1); const middle = Math.floor((finite.length - 1) / 2); const median = finite.length % 2 ? finite[middle] : (finite[middle] + finite[middle + 1]) / 2;
  if (Math.abs(high - low) < 0.005) return `${usd(low)} in every season`;
  const middleText = finite.length < 3 ? '' : loss && median < 0 ? `, median gain ${usd(-median)}` : `, median ${loss ? 'loss ' : ''}${usd(median)}`;
  if (loss && low < 0) return `from a gain of ${usd(-low)} to a loss of ${usd(high)}${middleText}`;
  return `${rangeText(low, high, usd)}${middleText}`;
}

function stepSection(title, hint, ...children) {
  const step = node('section', undefined, { class: 'step' }); step.append(node('h3', title));
  if (hint) step.append(node('p', hint, { class: 'hint' }));
  const body = node('div', undefined, { class: 'stack step-body' }); children.forEach((child) => child && body.append(child)); step.append(body);
  return step;
}

/* ------------------------------------------------------------------------
 * Page module.
 * --------------------------------------------------------------------- */

export function mountPortfolio({ bootstrap, scenario, loadObject, countyFor, pageLink }) {
  const books = bootstrap.objects.filter((object) => object.result_type === 'book');
  const bookRecords = new Map();
  const fetchBook = (key) => { if (!bookRecords.has(key)) bookRecords.set(key, loadObject(key)); return bookRecords.get(key); };

  /* ---- Step 1: start from a book ------------------------------------ */
  const cards = node('div', undefined, { class: 'cards', role: 'group', 'aria-label': 'Example books' });
  const bookStatus = node('p', '', { class: 'status', role: 'status' });
  const bookSummary = node('div', undefined, { class: 'stack', 'aria-live': 'polite', 'aria-label': 'Published result for the selected book' });
  const importInput = node('input', undefined, { type: 'file', accept: '.json,.csv', id: 'book-import' });
  const downloadTemplate = button('Download CSV template', { quiet: true, small: true });
  function markCard(key) { cards.querySelectorAll('.card').forEach((card) => card.setAttribute('aria-pressed', String(card.dataset.book === key))); }
  function makeCard(key, title, description) {
    const card = node('button', undefined, { type: 'button', class: 'card', 'data-book': key, 'aria-pressed': 'false' });
    card.append(node('strong', title), node('p', description)); cards.append(card); return card;
  }

  /* ---- Step 2: holdings ---------------------------------------------- */
  const HOLDING_FIELDS = [
    ['row_id', 'Row', 'row'], ['kind', 'Kind of holding', 'kind'], ['entity_id', 'Location and index', 'medium'], ['amount', 'Amount', 'num'], ['budget', 'Baseline degree days', 'num'],
    ['candidate_id', 'Hedge candidate', 'long'], ['payoff_kind', 'Payoff', 'short'], ['strike', 'Strike', 'num'],
  ];
  const rows = node('tbody'); const holdingTable = node('table', undefined, { class: 'metric-table holdings-table' }); const tableHead = node('thead'); const headRow = node('tr');
  HOLDING_FIELDS.forEach(([, label, size]) => headRow.append(node('th', label, { class: size === 'num' ? 'num' : '' }))); tableHead.append(headRow); holdingTable.append(tableHead, rows);
  const holdingRegion = node('div', undefined, { class: 'table-wrap', role: 'region', 'aria-label': 'Editable holdings table' }); holdingRegion.append(holdingTable);
  const holdingsEmpty = node('p', 'No holdings yet. Add a row, import a file, or pick an example book above.', { class: 'status' });
  const holdingsStatus = node('p', '', { class: 'status', role: 'status' });
  const addHolding = button('Add holding row', { quiet: true });

  /* ---- Step 3: hedging rules ----------------------------------------- */
  const objective = node('select', undefined, { id: 'objective' }); OBJECTIVES.forEach(([value, label]) => objective.append(node('option', label, { value })));
  const esTarget = node('input', undefined, { type: 'number', inputmode: 'decimal', placeholder: 'Optional, in dollars', id: 'es-target' });
  const cashBudget = node('input', undefined, { type: 'number', inputmode: 'decimal', placeholder: 'Optional, in dollars', id: 'cash-budget' });
  const maxStations = node('input', undefined, { type: 'number', min: '1', placeholder: 'Optional', id: 'max-stations' });
  const costMultiplier = node('input', undefined, { type: 'number', min: '0', step: '0.01', value: '1', id: 'cost-multiplier' });
  const lots = node('input', undefined, { type: 'checkbox', id: 'lots' });
  const candidateChoices = node('fieldset', undefined, { class: 'candidate-choices' });
  const candidateList = node('div', undefined, { class: 'stack check-list' });
  candidateChoices.append(node('legend', 'Hedge candidates'), node('p', 'Untick a contract to keep it out of the hedge.', { class: 'hint status' }), candidateList);

  /* ---- Step 4: run ---------------------------------------------------- */
  const evaluate = button('Evaluate'); const optimize = button('Optimise', { primary: true }); const cancel = button('Cancel', { quiet: true, disabled: 'disabled' });
  const status = node('p', '', { class: 'status', role: 'status', 'data-role': 'run-status' });
  const result = node('div', undefined, { class: 'stack portfolio-result', 'aria-live': 'polite', 'aria-label': 'Calculation result' });
  const exportButton = button('Save book (JSON)', { quiet: true });
  const exportDecision = button('Decision record (JSON)', { disabled: 'disabled' }); const exportMemo = button('Decision memo (Markdown)', { disabled: 'disabled' });
  const exportPositions = button('Positions (CSV)', { disabled: 'disabled' }); const exportRows = button('Season losses (CSV)', { disabled: 'disabled' }); const exportHoldings = button('Holdings (CSV)', { disabled: 'disabled' });

  let localBook = { schema_version: '2.0', release_id: scenario.releaseId, holdings: [] }; let localBookRecord; let holdingsDirty = false; let displayedResultStale = false;
  let acceptedDecision;

  /** Hedge rows in the holdings take precedence over a book's published candidates, exactly as the compiler treats them. */
  function candidateIdsFor(book = localBook) { const explicit = (book.holdings || []).map((row) => row.candidate_id).filter(Boolean); return [...new Set(explicit.length ? explicit : book.candidate_ids || (book.candidate_contracts ? Object.keys(book.candidate_contracts) : []))]; }
  function candidateContract(id, book = localBook) {
    const contracts = book.candidate_contracts; const published = Array.isArray(contracts) ? contracts.find((contract) => contract.candidate_id === id) : contracts?.[id];
    return published || (book.holdings || []).find((row) => row.candidate_id === id) || null;
  }
  function candidateWords(id, book = localBook) {
    const contract = candidateContract(id, book);
    if (!contract) return { station: 'Imported contract', contract: `Candidate ${shortId(id)}` };
    return { station: placeLabel(contract.station_entity_id || contract.entity_id, countyFor), contract: contractSentence(contract) };
  }
  function renderCandidateChoices() {
    candidateList.replaceChildren(); const ids = candidateIdsFor();
    if (!ids.length) { candidateList.append(node('p', 'The contracts of an example or imported book will appear here.', { class: 'status' })); return; }
    ids.forEach((id) => {
      const words = candidateWords(id); const check = node('input', undefined, { type: 'checkbox', checked: 'checked', value: id, 'aria-label': `Include ${words.station}: ${words.contract}` });
      check.addEventListener('change', invalidateDecision);
      const label = node('label', undefined, { class: 'check' }); const text = node('span'); text.append(node('strong', words.station), document.createTextNode(` · ${words.contract}`)); label.append(check, text); candidateList.append(label);
    });
  }
  function selectedCandidateIds() { const checks = [...candidateList.querySelectorAll('input[type=checkbox]')]; return checks.filter((check) => check.checked).map((check) => check.value); }
  const NEEDS_ES_TARGET = 'Optimise is unavailable until you set an ES90 target: the minimise-cost objective has to be told what worst-10% average loss you can accept.';
  function updateOptimizeAvailability() {
    const blocked = objective.value === 'min_cost_es' && (esTarget.value === '' || !Number.isFinite(Number(esTarget.value)));
    optimize.disabled = blocked;
    if (blocked) { status.textContent = NEEDS_ES_TARGET; status.classList.remove('status-error'); }
    else if (status.textContent === NEEDS_ES_TARGET) status.textContent = '';
  }
  function setExports(enabled) { [exportDecision, exportMemo, exportPositions, exportRows, exportHoldings].forEach((control) => (enabled ? control.removeAttribute('disabled') : control.setAttribute('disabled', 'disabled'))); }
  function clearStaleNotices() { [result, bookSummary].forEach((holder) => holder.querySelectorAll('[data-role="stale-notice"]').forEach((notice) => notice.remove())); displayedResultStale = false; }
  function invalidateDecision() {
    acceptedDecision = undefined; setExports(false);
    if (!displayedResultStale && (result.hasChildNodes() || bookSummary.hasChildNodes())) {
      const notice = () => node('p', 'An input or rule changed since this result was calculated. Run the calculation again before using or exporting it.', { class: 'notice', 'data-role': 'stale-notice' });
      if (result.hasChildNodes()) result.prepend(notice());
      if (bookSummary.hasChildNodes()) bookSummary.prepend(notice());
      displayedResultStale = true;
    }
  }
  objective.addEventListener('change', () => { updateOptimizeAvailability(); invalidateDecision(); }); esTarget.addEventListener('input', () => { updateOptimizeAvailability(); invalidateDecision(); }); cashBudget.addEventListener('input', invalidateDecision); maxStations.addEventListener('input', invalidateDecision); lots.addEventListener('change', invalidateDecision); costMultiplier.addEventListener('input', invalidateDecision); updateOptimizeAvailability();

  /** Which of the four plain kinds a stored row is, without rewriting the row. */
  function holdingKind(holding) {
    if (holding.candidate_id || holding.kind === 'hedge') return 'hedge';
    const stored = holding.loss_kind || holding.kind;
    if (stored === 'contract_payoff' || holding.kind === 'claim') return 'claim';
    return stored || 'heating_shortfall';
  }
  function kindControl(holding, label) {
    const current = holdingKind(holding);
    const select = node('select', undefined, { class: 'control', 'data-size': 'kind', 'aria-label': `${holding.row_id || 'Row'} ${label.toLowerCase()}` });
    const options = HOLDING_KINDS.some(([code]) => code === current) ? HOLDING_KINDS : [...HOLDING_KINDS, [current, humanize(current)]];
    options.forEach(([code, text]) => select.append(node('option', text, { value: code })));
    select.value = current;
    select.addEventListener('change', () => {
      holdingsDirty = true; invalidateDecision(); holding.kind = select.value;
      if (select.value === 'hedge') delete holding.loss_kind;
      else holding.loss_kind = select.value === 'claim' ? 'contract_payoff' : select.value;
    });
    return select;
  }
  function fieldControl(holding, fieldName, label, size) {
    const current = fieldName === 'payoff_kind' ? holding.payoff_spec?.kind : fieldName === 'strike' ? holding.payoff_spec?.strike : holding[fieldName];
    const shown = fieldName === 'budget' ? cellNumber(current, 1) : fieldName === 'amount' || fieldName === 'strike' ? cellNumber(current) : current ?? '';
    const input = node('input', undefined, { value: shown, 'aria-label': `${holding.row_id || 'Row'} ${label.toLowerCase()}`, class: 'control', 'data-size': size, ...(size === 'num' ? { inputmode: 'decimal' } : {}) });
    input.addEventListener('change', () => {
      holdingsDirty = true; invalidateDecision();
      if (fieldName === 'payoff_kind' || fieldName === 'strike') { holding.payoff_spec ||= {}; holding.payoff_spec[fieldName === 'payoff_kind' ? 'kind' : 'strike'] = fieldName === 'strike' ? readNumber(input.value) : input.value; }
      else holding[fieldName] = ['amount', 'budget'].includes(fieldName) ? readNumber(input.value) : input.value;
    });
    return input;
  }
  function renderHoldings(holdings = []) {
    rows.replaceChildren(); holdingsEmpty.classList.toggle('hidden', holdings.length > 0); holdingRegion.classList.toggle('hidden', holdings.length === 0);
    holdings.forEach((holding) => {
      const row = node('tr');
      HOLDING_FIELDS.forEach(([fieldName, label, size]) => {
        const cell = node('td', undefined, { class: size === 'num' ? 'num' : '' });
        cell.append(fieldName === 'kind' ? kindControl(holding, label) : fieldControl(holding, fieldName, label, size));
        row.append(cell);
      });
      rows.append(row);
    });
  }
  addHolding.addEventListener('click', () => { holdingsDirty = true; invalidateDecision(); localBook.holdings ||= []; localBook.holdings.push({ row_id: `local-${localBook.holdings.length + 1}`, kind: 'heating_shortfall', entity_id: '', amount: 0, budget: 0, units: 'USD', currency: 'USD' }); renderHoldings(localBook.holdings); renderCandidateChoices(); });
  downloadTemplate.addEventListener('click', () => download(holdingsTemplate(), 'weather-basis-holdings-template.csv', 'text/csv'));

  /* ---- Published book summary ----------------------------------------- */
  function renderPublished(record, book) {
    const optimized = book.optimized || {}; const risk = optimized.risk || {}; const baseline = book.baseline || {}; const frontier = book.frontier || {}; const incremental = book.incremental_claim || {}; const diversification = book.natural_diversification || {}; const predictive = book.predictive_components || {};
    const unhedged = baseline.unhedged_es; const hedged = risk.expected_shortfall;
    const reduction = isFinite_(unhedged) && isFinite_(hedged) && Number(unhedged) > 0 ? 1 - Number(hedged) / Number(unhedged) : null;
    const parts = [];
    parts.push(node('p', `Published result for ${bookTitle(record.object_key, book).toLowerCase()} over ${num(book.scenario_count)} simulated seasons. ES90 is the ${ES_MEANING}.`, { class: 'status' }));
    parts.push(tiles([
      tile('ES90 with no hedge', usd(unhedged), `${ES_MEANING}, before any protection`),
      tile('ES90 with the published hedge', usd(hedged), reduction != null ? `${pct(reduction, 0)} lower, after paying for the hedge` : statusWord(optimized.status)),
      tile('Cost of the hedge', usd(optimized.deterministic_cost), 'illustrative premium plus fees, paid every season'),
      tile('Objective', objectiveLabel(optimized.objective), statusWord(optimized.status), { small: true }),
    ]));
    const ids = candidateIdsFor(book); const positions = Array.isArray(optimized.positions) ? optimized.positions : [];
    if (ids.length) {
      const table = dataTable(['Station', 'Contract', 'Position', 'Unit cost'], ids.map((id, index) => { const words = candidateWords(id, book); const position = positions[index]; const row = [words.station, words.contract, positionText(position), usd(book.candidate_unit_costs?.[id])]; row.__class = isFinite_(position) && Math.abs(Number(position)) < 1e-9 ? 'is-muted' : ''; return row; }), { numeric: [2, 3] });
      table.classList.add('positions-table');
      const block = node('div', undefined, { class: 'stack' }); block.append(node('h4', 'What was hedged'), table); parts.push(block);
    }
    if (isFinite_(incremental.incremental_es) || isFinite_(incremental.incremental_cost)) parts.push(node('p', `Adding the new claim to the existing book raises its ES90 by ${usd(incremental.incremental_es)} and the cost of hedging it by ${usd(incremental.incremental_cost)}.`));
    if (isFinite_(diversification.gross_book_es)) parts.push(node('p', `Natural diversification: held together, these exposures have an ES90 of ${usd(diversification.gross_book_es)}, ${usd(diversification.sum_standalone_es_minus_gross_book_es)} less than the sum of each exposure on its own. That is a description of the book, not a hedge.`));
    if (book.cost_policy) {
      const fee = book.cost_policy.contract_fee_usd;
      parts.push(node('p', `How the hedge is priced: each contract's illustrative premium is its average payout across the ${num(book.scenario_count)} simulated seasons, plus a fixed ${isFinite_(fee) ? usd(fee) : 'flat'} fee per contract. These are model prices, not market quotes.`, { class: 'callout' }));
    }
    const points = Array.isArray(frontier.points) ? frontier.points : [];
    if (points.length) {
      const details = node('details', undefined, { class: 'plain' }); details.append(node('summary', 'Published frontier: what each level of spending buys'));
      const reference = isFinite_(unhedged) ? unhedged : points.map((point) => point.risk?.expected_shortfall).find(isFinite_);
      details.append(dataTable(['Cost of the hedge', 'ES90', 'Change from no hedge'], points.map((point) => {
        const es = point.risk?.expected_shortfall;
        return [usd(point.deterministic_cost), usd(es), point.status && point.status !== 'optimal' ? statusWord(point.status) : changeWords(reference, es)];
      }), { numeric: [0, 1, 2] }));
      parts.push(details);
    }
    if (Object.keys(predictive).length) {
      const details = node('details', undefined, { class: 'plain' }); details.append(node('summary', 'Where the money goes across the simulated seasons'));
      details.append(kvTable([['Loss on the exposures', distributionEntry(predictive.gross_exposure_loss)], ['Hedge payoff', distributionEntry(predictive.hedge_payoff)], ['Cost of the hedge', distributionEntry(predictive.frozen_cost)], ['Net loss', distributionEntry(predictive.total_loss, { loss: true })]]));
      parts.push(details);
    }
    parts.push(envelopeProvenance(record, [['Book', book.book_id], ['Book result', book.result_id], ['Scenario artifact', book.scenario_artifact_id], ['Cost profile', book.cost_policy?.cost_profile_id], ['Cost profile description', book.cost_policy?.description], ['Candidate contracts', book.candidate_ids], ['Published status', record.status]]));
    bookSummary.replaceChildren(...parts);
  }

  /** Nothing from the previous book may keep standing once another one is chosen. */
  function clearRunState() { acceptedDecision = undefined; setExports(false); result.replaceChildren(); bookSummary.replaceChildren(); displayedResultStale = false; status.textContent = ''; status.classList.remove('status-error'); }
  async function selectBook(key) {
    markCard(key);
    if (!key) { localBook = { schema_version: '2.0', release_id: scenario.releaseId, holdings: [] }; localBookRecord = undefined; holdingsDirty = true; clearRunState(); bookStatus.textContent = 'Empty book. Add holdings in step 2, or import a file.'; renderHoldings(localBook.holdings || []); renderCandidateChoices(); updateOptimizeAvailability(); document.dispatchEvent(new Event('wba-book-change')); return; }
    bookStatus.textContent = 'Loading the example book…';
    clearRunState();
    try {
      const record = await fetchBook(key); localBook = record.payload; localBookRecord = record; holdingsDirty = false; clearRunState(); objective.value = localBook.objective || 'es'; updateOptimizeAvailability(); renderHoldings(localBook.holdings || []); renderCandidateChoices();
      renderPublished(record, localBook);
      bookStatus.textContent = 'Example book loaded with its published result. Edit the holdings or rules below and run your own calculation on the same simulated seasons.';
      document.dispatchEvent(new Event('wba-book-change'));
    } catch (error) { bookStatus.textContent = `This book could not be loaded: ${error.message}`; }
  }

  books.forEach((book) => {
    const key = book.object_key || book.object_id; const card = makeCard(key, bookTitle(key), 'Loading its holdings…');
    card.addEventListener('click', () => selectBook(key));
    fetchBook(key).then((record) => { card.querySelector('p').textContent = bookDescription(record.payload || {}, countyFor, candidateIdsFor(record.payload || {}).length); }).catch(() => { card.querySelector('p').textContent = 'The published book could not be loaded.'; });
  });
  const emptyCard = makeCard('', 'Empty book', 'Start from nothing and add your own holdings.'); emptyCard.addEventListener('click', () => selectBook(''));

  /* ---- Carried Contract Lab claim ------------------------------------ */
  const carriedMembers = scenario.contractMembers ? scenario.contractMembers.split(',').filter(Boolean).map((pair) => `${scenario.fips}:${pair}`) : [`${scenario.fips}:${scenario.indexId}`];
  const carriedKind = scenario.payoffFamily === 'capped_call' ? 'call' : scenario.payoffFamily === 'capped_put' ? 'put' : scenario.payoffFamily === 'spread' ? (Number(scenario.secondaryStrike) > Number(scenario.strike) ? 'call_spread' : 'put_spread') : scenario.payoffFamily;
  const carriedSpec = { kind: carriedKind, strike: scenario.strike, multiplier: scenario.multiplier, cap: scenario.cap, entry_level: scenario.strike, high_strike: scenario.secondaryStrike, low_strike: scenario.secondaryStrike, call_strike: scenario.secondaryStrike };
  const appendCarriedClaim = button('Add this claim to the holdings');
  const claimReady = scenario.strike !== null && scenario.multiplier !== null && Number.isFinite(Number(scenario.strike)) && Number.isFinite(Number(scenario.multiplier)) && Number(scenario.multiplier) > 0 && carriedMembers.length >= 1 && carriedMembers.length <= 12;
  const carriedContract = node('div', undefined, { class: claimReady ? 'callout callout-info stack' : 'status' });
  if (claimReady) {
    const county = countyLabel(countyFor?.(scenario.fips), scenario.fips);
    const memberText = carriedMembers.length > 1 ? `${carriedMembers.length} months (${joinList(carriedMembers.map((member) => pairLabel(entityParts(member).pair, { short: true })))})` : pairLabel(entityParts(carriedMembers[0]).pair);
    const sentence = node('p'); sentence.append(node('strong', 'Contract from Contract Lab. '), document.createTextNode(`${PAYOFF_WORDS[carriedKind] || humanize(carriedKind)} on ${memberText} for ${county}, strike ${num(scenario.strike, 0)}, ${usd(scenario.multiplier)} per degree day${scenario.cap != null && scenario.cap !== '' ? `, capped at ${usd(scenario.cap)}` : ''}. Adding it makes it a claim you are liable for; it does not add or choose a hedge.`));
    const actions = node('div', undefined, { class: 'btn-row' }); actions.append(appendCarriedClaim);
    carriedContract.append(sentence, actions, provenanceBlock([['Source release', scenario.releaseId], ['Source scenario set', scenario.contractScenarioSetId || 'Resolved from the loaded scenario matrix'], ['Members', carriedMembers], ['Payoff structure', scenario.payoffStructure], ['Payoff specification', JSON.stringify(carriedSpec)], ['Direction', '1 (underwriter liability)']], { summary: 'Claim details' }));
  } else {
    appendCarriedClaim.disabled = true;
    carriedContract.append(document.createTextNode('To add a contract of your own design as a claim, price it in '), node('a', 'Contract Lab', { href: pageLink ? pageLink('contract.html') : 'contract.html' }), document.createTextNode(' first; it will appear here with a button that adds it.'));
  }
  appendCarriedClaim.addEventListener('click', () => { if (!claimReady) return; const rowId = `claim-${scenario.fips}-${scenario.indexId}-${(localBook.holdings || []).length + 1}`; localBook.holdings ||= []; localBook.holdings.push({ row_id: rowId, kind: 'claim', loss_kind: 'contract_payoff', entity_id: `${scenario.fips}:${scenario.indexId}`, member_entity_ids: carriedMembers, payoff_structure: scenario.payoffStructure, payoff_spec: carriedSpec, direction: 1, amount: Number(scenario.multiplier), budget: Number(scenario.strike), units: 'USD', currency: 'USD', source_release_id: scenario.releaseId, source_scenario_set_id: scenario.contractScenarioSetId || null }); holdingsDirty = true; invalidateDecision(); renderHoldings(localBook.holdings); renderCandidateChoices(); holdingsStatus.textContent = `Claim added to the holdings as row ${rowId}. Hedge candidates are unchanged.`; });

  /* ---- Import / export ------------------------------------------------ */
  importInput.addEventListener('change', async () => { const file = importInput.files?.[0]; if (!file) return; const text = await file.text(); if (file.name.endsWith('.json')) { try { const decoded = JSON.parse(text); if (decoded.decision_id) { if (decoded.decision_id !== await decisionIdentity(decoded)) throw new Error('identity mismatch'); acceptedDecision = decoded; localBook = decoded.request?.book || decoded.request || localBook; holdingsDirty = false; setExports(true); markCard(null); bookSummary.replaceChildren(); displayedResultStale = false; renderResult(acceptedDecision); bookStatus.textContent = 'Decision record restored without recalculation; its identity checked out. The result is shown in step 4.'; } else { localBook = decoded; holdingsDirty = true; markCard(null); bookSummary.replaceChildren(); bookStatus.textContent = 'Your book was loaded. It stays in this browser and is not published or shared.'; } renderHoldings(localBook.holdings || []); renderCandidateChoices(); } catch { bookStatus.textContent = 'The selected JSON is not a valid book or decision record, or its identity does not match its contents.'; } } else { const parsed = parseHoldingsCsv(text); if (parsed.errors.length) { bookStatus.textContent = `The CSV was not accepted: ${parsed.errors.join(' ')}`; return; } localBook.holdings = parsed.rows; holdingsDirty = true; renderHoldings(parsed.rows); renderCandidateChoices(); bookStatus.textContent = `${parsed.rows.length} holding row${parsed.rows.length === 1 ? '' : 's'} imported as written, without unit conversion or dropping locations.`; } document.dispatchEvent(new Event('wba-book-change')); });
  exportButton.addEventListener('click', () => download(JSON.stringify(localBook, null, 2), 'weather-basis-book.json'));
  exportDecision.addEventListener('click', () => { if (acceptedDecision) download(JSON.stringify(acceptedDecision, null, 2), 'weather-basis-decision.json'); });
  exportMemo.addEventListener('click', () => { if (acceptedDecision) download(decisionMemo(acceptedDecision), 'weather-basis-decision-memo.md', 'text/markdown'); });
  exportPositions.addEventListener('click', () => { if (acceptedDecision) download(csv([['candidate_id', 'position'], ...(acceptedDecision.request?.problem?.candidate_ids || []).map((id, index) => [id, acceptedDecision.result?.positions?.[index]])]), 'weather-basis-accepted-positions.csv', 'text/csv'); });
  exportRows.addEventListener('click', () => { if (acceptedDecision) download(csv([['scenario_id', 'residual_loss'], ...(acceptedDecision.request?.problem?.scenario_ids || []).map((id, index) => [id, acceptedDecision.result?.residual_loss?.[index]])]), 'weather-basis-accepted-result-rows.csv', 'text/csv'); });
  exportHoldings.addEventListener('click', () => { if (acceptedDecision) { const holdings = acceptedDecision.request?.holdings || []; const columns = [...new Set(holdings.flatMap((row) => Object.keys(row)))]; download(csv([columns, ...holdings.map((row) => columns.map((column) => typeof row[column] === 'object' ? JSON.stringify(row[column]) : row[column]))]), 'weather-basis-accepted-holdings.csv', 'text/csv'); } });

  /* ---- Result rendering ------------------------------------------------ */
  /** Which rule, if any, held the answer back — and for a floor at zero, which station it kept out. */
  function bindingWords(binding, ids, positions, book) {
    if (!binding.length) return 'No rule was binding: the hedge had room to spare under every constraint.';
    const idle = ids.filter((id, index) => isFinite_(positions[index]) && Math.abs(Number(positions[index])) < 1e-9)
      .map((id) => { const contract = candidateContract(id, book); const entity = contract?.station_entity_id || contract?.entity_id; return stationId(entity) ? stationCity(entity) : candidateWords(id, book).station; });
    const phrases = binding.map((key) => (key === 'lower_bounds' && idle.length ? `${constraintWord(key)} (the optimiser would otherwise have sold ${joinList(idle)} short)` : constraintWord(key)));
    const opener = binding.length === 1 ? 'One rule' : binding.length === 2 ? 'Two rules' : `${num(binding.length)} rules`;
    return `${opener} shaped this result: ${joinList(phrases)}. Loosening ${binding.length === 1 ? 'it' : 'them'} would change the answer.`;
  }
  function renderResult(record) {
    const output = record.result || {}; const request = record.request || {}; const problem = request.problem || {}; const baseline = record.baseline || {}; const book = request.book || localBook;
    const parts = [];
    const baselineEs = baseline.risk?.expected_shortfall; const hedgedEs = output.risk?.expected_shortfall; const cost = output.deterministic_cost;
    const change = esChange(baselineEs, hedgedEs); const solved = output.status === 'optimal' || output.status === 'available';
    if (solved && isFinite_(baselineEs) && isFinite_(hedgedEs)) {
      const sentence = node('p', undefined, { class: 'sentence' });
      sentence.append(document.createTextNode(`${output.status === 'available' ? 'With the positions as they stand' : 'With this hedge'}, the ${ES_MEANING} goes from `), node('strong', usd(baselineEs)), document.createTextNode(' with no hedge to '), node('strong', usd(hedgedEs)), document.createTextNode(change ? ` (${change.text})` : ''), document.createTextNode(isFinite_(cost) ? `, for an illustrative hedge cost of ${usd(cost)} a season.` : '.'));
      parts.push(sentence);
    }
    const resultSub = solved ? `${objectiveLabel(output.objective)}; ${request.lots ? 'whole contract lots' : 'fractional contracts allowed'}` : REASON_SUBS[output.reason_code] !== undefined ? REASON_SUBS[output.reason_code] : output.reason_code ? statusText(output.reason_code) : null;
    const costSub = solved || isFinite_(cost) ? 'illustrative premium plus fees, paid every season' : 'no hedge to price';
    parts.push(tiles([
      tile('ES90 with no hedge', usd(baselineEs), `${ES_MEANING}, before any protection`),
      tile('ES90 with this hedge', usd(hedgedEs), change ? change.text : isFinite_(hedgedEs) ? ES_MEANING : statusWord(output.status)),
      tile('Cost of the hedge', usd(cost), costSub),
      tile('Result', statusWord(output.status), resultSub, { small: true }),
    ]));
    if (output.status === 'infeasible') parts.push(node('p', 'None of the ticked contracts can meet these rules. Raise the ES90 target, lift the cash budget or the maximum stations, or tick more candidates, then run again.', { class: 'callout callout-warn' }));
    const ids = Array.isArray(problem.candidate_ids) ? problem.candidate_ids : []; const positions = Array.isArray(output.positions) ? output.positions : [];
    if (ids.length && output.status !== 'infeasible') {
      const block = node('div', undefined, { class: 'stack' }); block.append(node('h4', 'Positions'), node('p', 'How many of each station contract the hedge holds; greyed rows are contracts left unused.', { class: 'status' }));
      const table = dataTable(['Station', 'Contract', 'Position', 'Unit cost'], ids.map((id, index) => { const words = candidateWords(id, book); const position = positions[index]; const row = [words.station, words.contract, positionText(position), usd(problem.unit_costs?.[index])]; row.__class = isFinite_(position) && Math.abs(Number(position)) < 1e-9 ? 'is-muted' : ''; return row; }), { numeric: [2, 3] });
      table.classList.add('positions-table'); block.append(table);
      parts.push(block);
    }
    const adverse = Array.isArray(record.adverse_scenarios) ? record.adverse_scenarios : [];
    if (adverse.length) {
      const block = node('div', undefined, { class: 'stack' }); block.append(node('h4', 'Most adverse simulated seasons'), node('p', 'The three simulated seasons that still lose the most with this hedge in place.', { class: 'status' }));
      block.append(dataTable(['Season', 'Loss after hedging'], adverse.map((row, rank) => [adverseLabel(row.scenario_id, rank), usd(row.residual_loss)]), { numeric: [1] }));
      parts.push(block);
    }
    const constraints = constraintSummary(output.constraint_residuals);
    if (constraints.entries.length) parts.push(node('p', bindingWords(constraints.binding, ids, positions, book)));
    parts.push(provenanceBlock([['Decision', record.decision_id], ['Input hash', request.input_hash], ['Release', record.release_id], ['Scenario set', record.scenario_set_id], ['Scenario sample', problem.scenario_ids?.length ? `${problem.scenario_ids.length} seasons` : null], ['Solver', output.solver], ['Objects', record.object_ids], ['Sources', record.source_artifact_ids], ['Models', record.model_spec_ids], ['Candidate contracts', ids], ['Most adverse seasons', adverse.map((row) => row.scenario_id)], ['Constraint residuals', output.constraint_residuals ? JSON.stringify(output.constraint_residuals) : null]], { summary: 'Decision identity and provenance' }));
    result.replaceChildren(...parts);
  }

  /* ---- Calculation --------------------------------------------------- */
  let worker; let activeRequest;
  async function problemForBook(kernel, overrides) { const holdings = localBook.holdings || []; const fips = [...new Set(holdings.filter((holding) => !holding.candidate_id).flatMap((holding) => [holding.entity_id, ...(holding.member_entity_ids || [])]).map((entityId) => String(entityId).match(/\d{5}/)?.[0]).filter(Boolean))]; if (!fips.length) throw new Error('Add an exposure or claim holding before calculation.'); const [stationMatrix, ...countyMatrices] = await Promise.all([loadObject('station_scenarios'), ...fips.map((id) => loadObject(`county_scenarios:${id}`))]); const records = [localBookRecord, stationMatrix, ...countyMatrices].filter(Boolean); const ids = (field) => [...new Set(records.flatMap((record) => { const value = record[field] ?? record[field.endsWith('_ids') ? field.slice(0, -1) : field]; return Array.isArray(value) ? value : value ? [value] : []; }))]; return { problem: compileHoldingsProblem({ book: localBook, holdings, countyMatrices, stationMatrix, kernel, problem: overrides }), source_artifact_ids: ids('source_artifact_ids'), model_spec_ids: ids('model_spec_ids'), object_ids: records.map((record) => record.object_id).filter(Boolean) }; }
  /** What is missing before anything can be calculated, as plain sentences (empty when the book is complete enough to try). */
  function holdingsGaps() {
    const holdings = localBook.holdings || []; const exposures = holdings.filter((holding) => !holding.candidate_id); const hedges = holdings.filter((holding) => holding.candidate_id); const gaps = [];
    if (!holdings.length) return ['There are no holdings yet. Add a row in step 2, import a file, or pick an example book in step 1.'];
    const rowNames = (list) => joinList(list.map((holding) => holding.row_id || holding.candidate_id || 'without a name'));
    const unplaced = exposures.filter((holding) => !String(holding.entity_id ?? '').trim());
    if (unplaced.length) gaps.push(`${unplaced.length === 1 ? 'Row' : 'Rows'} ${rowNames(unplaced)} need${unplaced.length === 1 ? 's' : ''} a location and index: a county FIPS code and month such as 31109:HDD-01.`);
    const unplacedHedges = hedges.filter((holding) => !String(holding.entity_id ?? '').trim());
    if (unplacedHedges.length) gaps.push(`Hedge ${unplacedHedges.length === 1 ? 'row' : 'rows'} ${rowNames(unplacedHedges)} need${unplacedHedges.length === 1 ? 's' : ''} a station index, as in the CSV template.`);
    if (!exposures.length) gaps.push('The book has hedges but nothing to protect: add at least one exposure or claim row.');
    if (!candidateIdsFor().length) gaps.push('There are no hedge candidates to choose from: add hedge rows to the holdings, import the CSV template, or start from an example book.');
    return gaps.length ? ['The book cannot be calculated yet.', ...gaps] : [];
  }
  async function calculate(type) {
    status.classList.remove('status-error'); cancel.disabled = false;
    try {
      const gaps = holdingsGaps(); if (gaps.length) throw Object.assign(new Error(gaps.join(' ')), { friendly: true });
      if (type === 'optimize' && objective.value === 'min_cost_es' && (esTarget.value === '' || !Number.isFinite(Number(esTarget.value)))) throw new Error('Minimum-cost ES requires an expected-shortfall target.');
      const kernel = await portfolioKernel(); const excluded = new Set(); const selected = selectedCandidateIds().filter((id) => !excluded.has(id)); if (!selected.length && candidateIdsFor().length) throw new Error('Select at least one hedge candidate.');
      const overrides = { ...(cashBudget.value === '' ? {} : { cash_budget: Number(cashBudget.value) }), ...(maxStations.value === '' ? {} : { max_stations: Number(maxStations.value) }), ...(costMultiplier.value === '' ? {} : { cost_multiplier: Number(costMultiplier.value) }), ...(selected.length ? { candidate_ids: selected } : {}) };
      const compiled = await problemForBook(kernel, overrides); const problem = replayProblem(compiled.problem);
      worker ||= new Worker(new URL('../workers/portfolio-worker.js', import.meta.url));
      const inputHash = kernel.stableHash(problem); const requestId = crypto.randomUUID(); activeRequest = { requestId, inputHash };
      await workerRequest(worker, { type: 'initialize', request_id: requestId, input_hash: inputHash, schema_version: '2.0', payload: {} });
      const request = { type, request_id: crypto.randomUUID(), input_hash: inputHash, schema_version: '2.0', payload: type === 'evaluate' ? { problem, positions: localBook.positions || Array(problem.candidate_ids.length).fill(0), alpha: 0.90 } : { problem, objective: objective.value, alpha: 0.90, es_target: esTarget.value === '' ? undefined : Number(esTarget.value), lots: lots.checked } };
      activeRequest = { requestId: request.request_id, inputHash };
      status.textContent = `${type === 'evaluate' ? 'Evaluating the current positions' : 'Searching for the best hedge'} across ${num(problem.scenario_ids?.length)} simulated seasons…`;
      const output = await workerRequest(worker, request);
      if (activeRequest.requestId !== request.request_id) return;
      clearStaleNotices();
      const baseline = kernel.evaluate(problem, Array(problem.candidate_ids.length).fill(0), request.payload.alpha);
      acceptedDecision = jsonSafe({ schema_version: '2.0', question: `${type} ${objective.value} local weather-basis portfolio`, release_id: scenario.releaseId, request: { book: localBook, problem, candidate_ids: problem.candidate_ids, input_hash: inputHash, holdings: localBook.holdings || [], objective: objective.value, es_target: request.payload.es_target, cash_budget: problem.cash_budget ?? null, cost_multiplier: overrides.cost_multiplier ?? 1, lots: Boolean(request.payload.lots) }, baseline, result: output, source_artifact_ids: compiled.source_artifact_ids, model_spec_ids: compiled.model_spec_ids, object_ids: compiled.object_ids, scenario_set_id: problem.scenario_set_id, uncertainty: 'Browser calculation from the release-pinned scenario inputs; no unpublished market or weather claim is added.', adverse_scenarios: adverseRows(problem, output) });
      acceptedDecision.decision_id = await decisionIdentity(acceptedDecision);
      setExports(true); renderResult(acceptedDecision);
      status.textContent = output.status === 'optimal' || output.status === 'available' ? `${statusWord(output.status)}. Save the decision record or its memo to restore this exact result later.` : `${statusWord(output.status)}. The decision record can still be saved.`;
    } catch (error) { status.textContent = error.friendly ? error.message : friendlyError(error.message); status.classList.add('status-error'); }
    cancel.disabled = true;
  }
  evaluate.addEventListener('click', () => calculate('evaluate')); optimize.addEventListener('click', () => calculate('optimize')); cancel.addEventListener('click', () => { if (cancel.disabled || !worker || !activeRequest) return; worker.postMessage({ type: 'cancel', request_id: crypto.randomUUID(), input_hash: activeRequest.inputHash, schema_version: '2.0', payload: { cancel_request_id: activeRequest.requestId } }); status.textContent = 'Cancellation requested.'; });

  /* ---- Scenario Room --------------------------------------------------- */
  const rooms = bootstrap.objects.filter((object) => object.result_type === 'scenario_room');
  let roomStep = null;
  if (rooms.length) {
    const roomSelect = node('select', undefined, { id: 'scenario-room-select' }); rooms.forEach((item) => { const key = item.object_key || item.object_id; roomSelect.append(node('option', roomName(key), { value: key })); });
    const roomResult = node('div', undefined, { class: 'stack', 'aria-live': 'polite', 'aria-label': 'Scenario Room result' });
    const renderRoom = async () => {
      try {
        const record = await loadObject(roomSelect.value); const payload = record.payload || {}; const set = payload.scenario_set || {}; const daily = payload.daily_temperature || {}; const monthly = payload.monthly_degree_days || {}; const source = payload.source_windows || []; const values = Array.isArray(daily.values) ? daily.values.flat(2).filter(Number.isFinite) : [];
        const option = [...roomSelect.options].find((item) => item.value === roomSelect.value); if (option) option.textContent = roomName(roomSelect.value, payload);
        const isStress = set.scenario_type === 'stress' || !Array.isArray(set.probability_weights);
        const units = daily.units === 'degF' ? '°F' : daily.units === 'degC' ? '°C' : daily.units || '';
        const facts = [
          ['Weather shown', weatherWords(payload)],
          ['Seasons', source.length ? source.map((item) => `${item.source_year || seasonLabel(item.scenario_id)} (${dateRange(item.window_start, item.window_end)})${item.source_historical_scenario_id ? ', built from the observed season' : ''}`).join('; ') : NA],
          ['Probability', isStress ? 'No probability attached: this is a what-if temperature shift, not a forecast.' : 'Each observed season counts equally. This is a record of what happened, not a forecast.'],
          ['Hedge cost', 'The hedge is charged the same illustrative premium as above; no market prices or risk measures are calculated for replayed weather.'],
          ['Daily temperature range', values.length ? `${rangeText(Math.min(...values), Math.max(...values), (value) => num(value))}${units ? ` ${units}` : ''}` : NA],
          ['Coverage', `${num(set.location_ids?.length)} locations; ${num(monthly.entity_ids?.length)} monthly county and station indexes`],
          ['Seasons left out', (payload.unavailable_windows || []).length ? payload.unavailable_windows.map(omittedSeasonWords).join(' ') : 'None'],
        ];
        const cashflowKey = roomSelect.value.replace(/^scenario_room:/, ''); const embedded = localBook.scenario_room_results?.[cashflowKey]; let cashflow = embedded; if (!cashflow && localBook.book_id) { try { cashflow = (await loadObject(`scenario_room_cashflows:${cashflowKey}:${localBook.book_id}`)).payload; } catch { try { cashflow = (await loadObject(`scenario_room_results:${localBook.book_id}:${cashflowKey}`)).payload; } catch {} } }
        const cashRows = cashflow?.rows || [];
        const parts = [kvTable(facts)];
        if (cashflow) {
          const totalLosses = cashRows.map((row) => Number((row.components || row).total_loss)).filter(Number.isFinite).sort((a, b) => a - b);
          const block = node('div', undefined, { class: 'stack' });
          block.append(node('h4', `Cashflows for ${localBook.book_id ? bookTitle('', localBook).toLowerCase() : 'this book'} under this weather`), node('p', `Each row replays the published hedge through one season of this weather, in dollars. ${isStress ? 'Stress rows carry no probability: they show what would happen, not how likely it is.' : 'Observed seasons are shown as they happened, with equal weight; they are not a forecast.'}`, { class: isStress ? 'callout callout-warn' : 'status' }));
          if (cashRows.length) block.append(dataTable(['Season', 'Loss on the exposures', 'Hedge payoff', 'Cost of the hedge', 'Net loss'], cashRows.map((entry) => { const components = entry.components || entry; return [seasonLabel(entry.scenario_id), usd(components.gross_exposure_loss), usd(components.hedge_payoff), usd(components.frozen_cost), usd(components.total_loss)]; }), { numeric: [1, 2, 3, 4] }));
          else block.append(node('p', 'No cashflow rows were published for this book and weather.', { class: 'status' }));
          const roomIds = Array.isArray(cashflow.candidate_ids) ? cashflow.candidate_ids : Object.keys(cashflow.candidate_contracts || {});
          const bookIds = candidateIdsFor(localBook); const bookPositions = Array.isArray(localBook.optimized?.positions) ? localBook.optimized.positions : [];
          const held = roomIds.filter((id) => { const index = bookIds.indexOf(id); return index >= 0 && isFinite_(bookPositions[index]) && Math.abs(Number(bookPositions[index])) > 1e-9; }).length;
          block.append(kvTable([
            ['Net loss across these seasons', distributionEntry(totalLosses, { loss: true })],
            ['Risk measures', cashflow.risk_metrics == null ? riskReasonWords(cashflow.risk_reason) : Object.entries(cashflow.risk_metrics).map(([key, value]) => `${humanize(key)}: ${isFinite_(value) ? usd(value) : value == null ? NA : String(value)}`).join('; ')],
            ['Contracts in use', bookPositions.length ? `${num(held)} of ${num(roomIds.length)} candidates` : `${num(roomIds.length)} candidates`],
          ]));
          parts.push(block);
        } else parts.push(node('p', 'Choose an example book in step 1 to see its published hedge replayed under this weather.', { class: 'status' }));
        parts.push(envelopeProvenance(record, [['Scenario set', set.scenario_set_id], ['Generator', set.generator_spec_id], ['Construction', payload.construction], ['Probability note as published', payload.probability_interpretation], ['Cost note as published', payload.cost_policy], ['Cashflow book result', cashflow?.book_result_id], ['Cashflow scenario set', cashflow?.room_scenario_set_id], ['Producer', cashflow?.producer]]));
        roomResult.replaceChildren(...parts);
      } catch (error) { roomResult.replaceChildren(node('p', `This weather surface could not be loaded: ${error.message}`, { class: 'status status-error' })); }
    };
    roomSelect.addEventListener('change', renderRoom); document.addEventListener('wba-book-change', renderRoom);
    roomStep = stepSection('Scenario Room', 'Replay a book\'s published hedge through observed or stylised weather. These are descriptions of particular seasons, not the 2,000-season simulation used above.', field('Weather to replay', roomSelect), roomResult);
    roomStep.id = 'scenario-room';
    renderRoom();
  }

  /* ---- Assemble the page ---------------------------------------------- */
  const importBlock = node('div', undefined, { class: 'import-block' });
  importBlock.append(field('Import a book, decision record or CSV', importInput, 'A book or decision record saved from this page (JSON), or a holdings spreadsheet (CSV). Files stay in your browser.'), downloadTemplate);
  const step1 = stepSection('Start from a book', 'Pick an example to see its published result, or begin with an empty book and your own file.', cards, importBlock, bookStatus, bookSummary);

  const holdingsNote = node('p', 'All amounts are US dollars per degree day.', { class: 'status holdings-note' });
  const holdingsHint = node('p', 'Amount is dollars per degree day. Baseline degree days is the level the exposure is measured from (the 30-year median for the example books). Location and index is a five-digit county FIPS code, a colon, then the month index \u2014 31109:HDD-01 is January heating degree days in Lancaster County, NE. Kind of holding is a heating exposure, a cooling exposure, a claim you are liable for, or a hedge you already hold.', { class: 'status' });
  const holdingsActions = node('div', undefined, { class: 'btn-row' }); holdingsActions.append(addHolding);
  const step2 = stepSection('Holdings', 'What you are exposed to. Each row is a county exposure, a claim you are liable for, or a hedge you already hold.', holdingsEmpty, holdingRegion, holdingsNote, holdingsHint, holdingsActions, holdingsStatus, carriedContract);

  const ruleFields = node('div', undefined, { class: 'field-row hedging-rules' });
  ruleFields.append(
    field('Objective', objective, 'What the optimiser tries to do.'),
    field('ES90 target', esTarget, 'Required for the minimise-cost objective; the worst-10% average loss you can accept.'),
    field('Cash budget', cashBudget, 'Most you will spend on premiums and fees, in dollars.'),
    field('Maximum stations', maxStations, 'Limit how many different stations the hedge may use.'),
    field('Cost multiplier', costMultiplier, 'Scales every illustrative premium; 1 keeps the published cost assumption.'),
  );
  const lotsLabel = node('label', undefined, { class: 'check' }); const lotsText = node('span'); lotsText.append(node('strong', 'Whole contract lots only'), document.createTextNode(' · the optimiser may only choose whole numbers of contracts')); lotsLabel.append(lots, lotsText);
  const step3 = stepSection('Hedging rules', 'Tell the optimiser what to minimise and what it may not exceed.', ruleFields, lotsLabel, candidateChoices);

  const runRow = node('div', undefined, { class: 'btn-row' }); runRow.append(optimize, evaluate, cancel);
  const exportRow = node('div', undefined, { class: 'btn-row' }); exportRow.append(exportDecision, exportMemo, exportPositions, exportRows, exportHoldings, exportButton);
  const exportBlock = node('div', undefined, { class: 'stack export-block' }); exportBlock.append(node('h4', 'Export'), node('p', 'The decision record is a complete account of this calculation. Its exports become available once a calculation has finished; the book itself can be saved at any time.', { class: 'status' }), exportRow);
  const step4 = stepSection('Run', `Optimise searches for the hedge that best meets the rules; Evaluate scores the positions as they stand. Everything runs in your browser on the 2,000 simulated seasons. ES90 is the ${ES_MEANING}.`, runRow, status, result, exportBlock, node('p', 'Files you import never leave this device. The optimiser will not run until every holding has a location, index and amount, and it says plainly when no hedge satisfies the rules.', { class: 'status' }));

  const steps = node('div', undefined, { class: 'steps' }); steps.append(step1, step2, step3, step4); if (roomStep) steps.append(roomStep);
  replacePanel('.lab-panel', [node('h2', 'Portfolio book'), steps]);
  renderHoldings(localBook.holdings || []); renderCandidateChoices();
}
