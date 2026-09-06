/** Contract Lab: design a weather contract and see what it would pay.
 *  The pricing path (payoff kinds, seasonal structures, station-linear hedge,
 *  customer load, export shape) is unchanged from V2; only the presentation is new. */
import { node, replacePanel } from './render.js';
import {
  NA, button, countyLabel, dataTable, dateRange, envelopeProvenance, field, kvTable, linkButton, monthName, num, pairLabel, pairParts, pct, rangeText, ratio, stationCity, stationLabel, statusText, tile, tiles, usd,
} from './format.js';

/* ---------- reference text ---------- */
const FAMILIES = [
  ['call', 'Call — pays when the index ends above the strike'],
  ['put', 'Put — pays when the index ends below the strike'],
  ['linear', 'Linear swap — pays above the strike, owes below it'],
  ['capped_call', 'Capped call — a call with a maximum payout'],
  ['capped_put', 'Capped put — a put with a maximum payout'],
  ['spread', 'Spread — pays between two strikes'],
  ['collar', 'Collar — a put at the strike, less a call at the second strike'],
];
const NEEDS_SECOND_STRIKE = ['spread', 'collar'];
const SECOND_STRIKE_HINT = { spread: 'Above the strike for a call spread, below it for a put spread', collar: 'The call strike; at or above the put strike' };
/* Plain names for the release's seasonal structures; the declared label is the fallback. */
const STRUCTURE_LABEL = { option_on_strip: (season) => `One option on the ${season} total`, sum_of_monthly_options: (season) => `Separate monthly options, ${season}, added together` };
/* The reference strike is published to full precision; show it to one decimal. Pricing always uses the value in the box. */
const displayStrike = (value) => (Number.isFinite(Number(value)) ? String(Math.round(Number(value) * 10) / 10) : '');
const MONTH_PLURAL = { January: 'Januaries', February: 'Februaries', March: 'Marches', April: 'Aprils', May: 'Mays', June: 'Junes', July: 'Julys', August: 'Augusts', September: 'Septembers', October: 'Octobers', November: 'Novembers', December: 'Decembers' };
const KIND_NOUN = { call: 'call', put: 'put', linear: 'swap', call_spread: 'call spread', put_spread: 'put spread', collar: 'collar' };
const TWO_STRIKE_KINDS = ['call_spread', 'put_spread', 'collar'];
const NUMBER_WORD = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve'];
const countWord = (n) => NUMBER_WORD[n] ?? num(n);
const capitalize = (text) => text.charAt(0).toUpperCase() + text.slice(1);
/* [pattern, plain message, ticket field the message belongs to (marked invalid and focused), or null]. */
const ERROR_TEXT = [
  [/requires a second strike/i, 'This payoff needs a second strike. Enter one under Payoff.', 'second'],
  [/high_strike above strike/i, 'For a call spread the second strike must be above the strike.', 'second'],
  [/low_strike below strike/i, 'For a put spread the second strike must be below the strike, so the two strikes cannot be equal.', 'second'],
  [/call_strike at or above put strike/i, 'For a collar the second strike (the call) must be at or above the strike (the put).', 'second'],
  [/requires finite strike|requires finite entry_level/i, 'Enter a strike in degree days.', 'strike'],
  [/invalid payoff multiplier|no valid payout multiplier/i, 'Enter a payout per degree day greater than zero.', 'multiplier'],
  [/cap must be finite/i, 'The cap must be zero or more dollars.', 'cap'],
  [/load must be finite/i, 'The loading must be a dollar amount.', 'load'],
  [/does not support this seasonal structure/i, 'This county and month have no seasonal structure of that kind in this release. Choose the single month instead.', 'structure'],
  [/seasonal member .* unavailable/i, 'One of the months in this seasonal structure has no simulated index for this county.', 'structure'],
  [/does not contain quote:/i, 'This release has no reference contract for this county and month. Choose another county or month on Explore.', null],
  [/does not contain county_scenarios/i, 'This release has no simulated seasons for this county.', null],
  [/not an aligned, identified public matrix/i, 'The simulated seasons for this county could not be verified, so nothing was priced.', null],
  [/kernel could not load/i, 'The payoff calculator could not load. Reload the page and try again.', null],
  [/integrity check failed/i, 'A data file failed its integrity check, so nothing was priced.', null],
];
const friendlyError = (error) => { const message = String(error?.message || error || ''); const match = ERROR_TEXT.find(([pattern]) => pattern.test(message)); return match ? { text: match[1], field: match[2] } : { text: `The ticket could not be priced: ${message}`, field: null }; };
const HEDGE_REASON = [
  [/coordinates differ/i, 'the station and county simulations do not share the same weather paths'],
  [/lacks declared seasonal member/i, 'the selected station has no simulated index for one of the months in this structure'],
  [/not an aligned, identified public matrix|does not contain station_scenarios/i, 'no simulated station paths are published in this release'],
];
const hedgeReason = (message) => { const match = HEDGE_REASON.find(([pattern]) => pattern.test(String(message || ''))); return match ? match[1] : 'the station hedge could not be computed on these paths'; };

/* ---------- small maths for presentation (never feeds the exported result) ---------- */
function quantile(values, q) { const sorted = values.filter(Number.isFinite).sort((a, b) => a - b); if (!sorted.length) return null; const pos = (sorted.length - 1) * q; const lo = Math.floor(pos); const hi = Math.ceil(pos); return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo); }
function niceTicks(min, max, count = 5) {
  const span = max - min || 1; const rough = span / count; const magnitude = 10 ** Math.floor(Math.log10(rough)); const residual = rough / magnitude;
  const step = (residual >= 5 ? 5 : residual >= 2 ? 2 : 1) * magnitude; const ticks = []; for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) ticks.push(Math.abs(v) < 1e-9 ? 0 : v); return ticks;
}

/* ---------- windows and season wording ---------- */
function windowFor(declared, structureValue) {
  const chosen = (declared.seasonal_structures || []).find((item) => item.aggregation === structureValue);
  const windows = chosen?.member_windows?.length ? chosen.member_windows : [declared.daily_window || {}];
  return { chosen, windows, start: windows.map((item) => item.start).filter(Boolean).sort()[0], end: windows.map((item) => item.end).filter(Boolean).sort().at(-1) };
}
const yearOf = (iso) => { const match = /^(\d{4})/.exec(String(iso || '')); return match ? match[1] : ''; };
const monthYear = (window) => { const month = monthName(window?.pair); const year = yearOf(window?.start); return month && year ? `${month} ${year}` : month || NA; };
function seasonLabel(windows, { short = false } = {}) {
  if (!windows?.length) return NA;
  if (windows.length === 1) return monthYear(windows[0]);
  const first = windows[0]; const last = windows.at(-1);
  if (short) return `${pairLabel(first.pair, { short: true }).split(' ')[0]} ${yearOf(first.start)} – ${pairLabel(last.pair, { short: true }).split(' ')[0]} ${yearOf(last.start)}`;
  return `${monthYear(first)} – ${monthYear(last)}`;
}
function seasonPlural(windows) { if (windows.length === 1) { const month = monthName(windows[0].pair); return MONTH_PLURAL[month] || 'seasons'; } return `${monthName(windows[0].pair)}–${monthName(windows.at(-1).pair)} seasons`; }
const indexKindWord = (indexId) => (pairParts(indexId)?.kind === 'CDD' ? 'cooling-degree-day' : 'heating-degree-day');
const pairKindWords = (indexId) => (pairParts(indexId)?.kind === 'CDD' ? 'cooling degree days' : 'heating degree days');

/* ---------- data access (unchanged from V2) ---------- */
async function kernel() { if (window.WbaPortfolio) return window.WbaPortfolio; await new Promise((resolve, reject) => { const script = node('script'); script.src = 'js/kernels/portfolio.js'; script.onload = resolve; script.onerror = () => reject(new Error('Payoff kernel could not load.')); document.head.append(script); }); return window.WbaPortfolio; }
function indexPaths(envelope, entityId) { const matrix = envelope.payload?.matrix || envelope.payload; const scenarioSet = envelope.payload?.scenario_set; const index = matrix.entity_ids?.indexOf(entityId); if (matrix?.schema_version !== '2.0' || matrix.matrix_kind !== 'aligned' || matrix.missing_support_policy !== 'reject' || !matrix.parent_scenario_set_id || !matrix.scenario_id_hash || !matrix.entity_id_hash || scenarioSet?.scenario_set_id !== matrix.parent_scenario_set_id || !matrix?.scenario_ids || index == null || index < 0) throw new Error('The county ScenarioMatrix is not an aligned, identified public matrix.'); return { ids: matrix.scenario_ids, values: matrix.values.map((row) => row[index]), scenarioSetId: matrix.parent_scenario_set_id }; }
function downloadDecision(value, filename) {
  const link = node('a'); const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }));
  link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** The V2 pricing path, verbatim: same inputs, same kernel calls, same outputs. */
async function calculate(next, loadValue, { scenario, loadObject, setScenario }) {
  const [quoteRecord, scenarios, payoffKernel] = await Promise.all([loadObject(`quote:${scenario.fips}:${scenario.indexId}`), loadObject(`county_scenarios:${scenario.fips}`), kernel()]);
  const ticket = quoteRecord.payload; const paths = indexPaths(scenarios, `${scenario.fips}:${scenario.indexId}`);
  const contractMultiplier = Number(next.multiplier ?? ticket?.option_contract?.payoff?.payout_usd_per_degree_day ?? ticket?.option_contract?.payout_usd_per_degree_day ?? ticket?.payout_usd_per_degree_day);
  if (!Number.isFinite(contractMultiplier) || contractMultiplier <= 0) throw new Error('The identified quote has no valid payout multiplier.');
  const spec = { strike: Number(next.strike ?? ticket?.option_contract?.payoff?.strike), entry_level: Number(next.strike ?? ticket?.option_contract?.payoff?.strike), multiplier: contractMultiplier, cap: next.cap ?? ticket?.option_contract?.payoff?.cap_usd ?? null, high_strike: Number(next.secondaryStrike), low_strike: Number(next.secondaryStrike), call_strike: Number(next.secondaryStrike) };
  const kind = next.payoffFamily === 'capped_put' ? 'put' : next.payoffFamily === 'capped_call' ? 'call' : next.payoffFamily === 'spread' ? (Number(next.secondaryStrike) > Number(next.strike) ? 'call_spread' : 'put_spread') : next.payoffFamily;
  if (['call_spread', 'put_spread', 'collar'].includes(kind) && !Number.isFinite(Number(next.secondaryStrike))) throw new Error('This payoff family requires a second strike.');
  const declared = ticket.option_contract || {}; const chosenStructure = (declared.seasonal_structures || []).find((item) => item.aggregation === next.payoffStructure); const members = chosenStructure?.member_pair_ids || [];
  if (next.payoffStructure !== 'monthly_option' && members.length) setScenario({ ...next, contractMembers: members.join(',') }, 'replaceState');
  const matrix = scenarios.payload?.matrix || scenarios.payload;
  const memberValues = members.map((pair) => { const column = matrix.entity_ids?.indexOf(`${scenario.fips}:${pair}`); if (column == null || column < 0) throw new Error(`Declared seasonal member ${pair} is unavailable in the aligned county matrix.`); return matrix.values.map((row) => row[column]); });
  let payoff;
  if (next.payoffStructure === 'monthly_option') payoff = payoffKernel.payoff(kind, paths.values, spec);
  else { if (!chosenStructure || !members.length) throw new Error('The identified quote does not support this seasonal structure.'); if (chosenStructure.aggregation === 'option_on_strip') payoff = payoffKernel.payoff(kind, paths.ids.map((_, row) => memberValues.reduce((sum, values) => sum + values[row], 0)), spec); else payoff = paths.ids.map((_, row) => memberValues.reduce((sum, values) => sum + payoffKernel.payoff(kind, [values[row]], spec)[0], 0)); }
  const expected = payoff.reduce((sum, value) => sum + value, 0) / payoff.length;
  let residual = null; let hedgeRatio = null; let hedgeFailure = null; const stationEntity = ticket.selection_asof?.selected_station_id;
  if (stationEntity) {
    try {
      const stationRecord = await loadObject('station_scenarios'); const stationPaths = indexPaths(stationRecord, stationEntity);
      if (stationPaths.scenarioSetId !== paths.scenarioSetId || stationPaths.ids.join('|') !== paths.ids.join('|')) throw new Error('station and county coordinates differ');
      const stationMatrix = stationRecord.payload?.matrix || stationRecord.payload; const stationId = String(stationEntity).split(':')[0];
      const stationMemberValues = members.map((pair) => { const column = stationMatrix.entity_ids?.indexOf(`${stationId}:${pair}`); if (column == null || column < 0) throw new Error(`Selected station lacks declared seasonal member ${pair}`); return stationMatrix.values.map((row) => row[column]); });
      const stationIndex = next.payoffStructure === 'monthly_option' ? stationPaths.values : stationPaths.ids.map((_, row) => stationMemberValues.reduce((sum, values) => sum + values[row], 0));
      const linearStationHedge = stationIndex.map((value) => value * contractMultiplier);
      const mean = (values) => values.reduce((sum, value) => sum + value, 0) / values.length; const countyMean = mean(payoff); const hedgeMean = mean(linearStationHedge); const centeredHedge = linearStationHedge.map((value) => value - hedgeMean); const variance = centeredHedge.reduce((sum, value) => sum + value ** 2, 0);
      if (variance > 0) { hedgeRatio = payoff.reduce((sum, value, row) => sum + (value - countyMean) * centeredHedge[row], 0) / variance; residual = payoff.map((value, row) => value - hedgeRatio * centeredHedge[row]); }
      else hedgeFailure = 'the station index does not vary across the simulated seasons';
    } catch (error) { residual = null; hedgeRatio = null; hedgeFailure = hedgeReason(error?.message); }
  } else hedgeFailure = 'no listed station was selected for this window';
  const enteredLoad = loadValue === '' ? null : Number(loadValue);
  if (enteredLoad !== null && !Number.isFinite(enteredLoad)) throw new Error('Customer-entered load must be finite USD.');
  const loadedExpected = enteredLoad === null ? null : expected + enteredLoad;
  const probability = payoff.filter((value) => value > 0).length / payoff.length;
  const isPayoffFunction = next.payoffStructure !== 'sum_of_monthly_options';
  const curveIndex = next.payoffStructure === 'monthly_option' ? paths.values : paths.ids.map((_, row) => memberValues.reduce((sum, values) => sum + values[row], 0));
  const shared = { ...scenario, ...next, contractMembers: members.length ? members.join(',') : null, contractScenarioSetId: paths.scenarioSetId };
  const { windows, start, end } = windowFor(declared, next.payoffStructure);
  return { next, quoteRecord, ticket, declared, chosenStructure, members, paths, contractMultiplier, spec, kind, payoff, expected, residual, hedgeRatio, hedgeFailure, stationEntity, enteredLoad, loadedExpected, probability, isPayoffFunction, curveIndex, shared, windows, dates: { start, end }, payoffKernel };
}

/* ---------- chart: index distribution with the payoff overlaid ---------- */
const COLOR = { ink: '#172c38', ink2: '#4f6167', muted: '#7b8a8e', line: '#cdd9d5', rule: '#a6c4c1', teal: '#195d70', paper: '#fbfcf8' };
function drawContractChart(canvas, { index, payoff, curve, markers, xTitle }) {
  const cssWidth = Math.max(300, Math.round(canvas.parentElement?.clientWidth || canvas.clientWidth || 900));
  const width = Math.min(900, cssWidth); const narrow = width < 520; const height = Math.round(Math.max(230, Math.min(360, width * 0.42)));
  canvas.width = width * 2; canvas.height = height * 2; canvas.style.aspectRatio = `${width} / ${height}`;
  const context = canvas.getContext('2d'); context.setTransform(1, 0, 0, 1, 0, 0); context.scale(2, 2); context.clearRect(0, 0, width, height); context.fillStyle = COLOR.paper; context.fillRect(0, 0, width, height);
  const fontSize = narrow ? 11 : 12; context.font = `${fontSize}px ui-sans-serif, system-ui, sans-serif`;
  const data = index.filter(Number.isFinite); const pay = payoff.filter(Number.isFinite); if (data.length < 2 || !pay.length) return false;
  const pad = { left: narrow ? 46 : 60, right: narrow ? 58 : 76, top: 22, bottom: narrow ? 42 : 48 }; const plotW = width - pad.left - pad.right; const plotH = height - pad.top - pad.bottom;
  const markerValues = markers.map((item) => item.value).filter(Number.isFinite);
  const rawMin = Math.min(...data, ...markerValues); const rawMax = Math.max(...data, ...markerValues); const xTicks = niceTicks(rawMin, rawMax, narrow ? 4 : 7); const lo = Math.min(rawMin, xTicks[0]); const hi = Math.max(rawMax, xTicks.at(-1));
  const bins = narrow ? 28 : 40; const binW = (hi - lo) / bins || 1; const counts = Array(bins).fill(0); data.forEach((value) => { counts[Math.min(bins - 1, Math.floor((value - lo) / binW))] += 1; }); const peak = Math.max(...counts);
  const leftTicks = niceTicks(0, peak, 4); const leftMax = Math.max(peak, leftTicks.at(-1));
  const curveYs = curve ? curve.map((point) => point.y).filter(Number.isFinite) : []; const pMin = Math.min(0, ...pay, ...curveYs); const pMax = Math.max(0, ...pay, ...curveYs); const rightTicks = niceTicks(pMin, pMax, narrow ? 4 : 5); const rLo = Math.min(pMin, rightTicks[0]); const rHi = Math.max(pMax, rightTicks.at(-1));
  const x = (value) => pad.left + (value - lo) / (hi - lo || 1) * plotW; const yLeft = (value) => pad.top + plotH - value / (leftMax || 1) * plotH; const yRight = (value) => pad.top + plotH - (value - rLo) / (rHi - rLo || 1) * plotH;
  context.textBaseline = 'middle';
  context.strokeStyle = COLOR.line; context.lineWidth = 1; context.fillStyle = COLOR.muted; context.textAlign = 'right';
  leftTicks.forEach((tick) => { const y = Math.round(yLeft(tick)) + .5; context.beginPath(); context.moveTo(pad.left, y); context.lineTo(width - pad.right, y); context.stroke(); context.fillText(num(tick), pad.left - 6, y); });
  context.fillStyle = COLOR.teal; context.globalAlpha = .42; counts.forEach((count, i) => { const left = x(lo + i * binW); const right = x(lo + (i + 1) * binW); context.fillRect(left + .5, yLeft(count), Math.max(1, right - left - 1), pad.top + plotH - yLeft(count)); }); context.globalAlpha = 1;
  if (rLo < 0 && rHi > 0) { const zero = Math.round(yRight(0)) + .5; context.strokeStyle = COLOR.rule; context.setLineDash([2, 3]); context.beginPath(); context.moveTo(pad.left, zero); context.lineTo(width - pad.right, zero); context.stroke(); context.setLineDash([]); }
  markers.forEach(({ value, label }, i) => { if (!Number.isFinite(value)) return; const mx = Math.round(x(value)) + .5; context.strokeStyle = COLOR.ink2; context.lineWidth = 1.5; context.setLineDash([5, 4]); context.beginPath(); context.moveTo(mx, pad.top); context.lineTo(mx, pad.top + plotH); context.stroke(); context.setLineDash([]); context.fillStyle = COLOR.ink2; const flip = mx > pad.left + plotW * .6; context.textAlign = flip ? 'right' : 'left'; context.fillText(label, mx + (flip ? -6 : 6), pad.top + 8 + i * (fontSize + 3)); });
  if (curve) { context.strokeStyle = COLOR.ink; context.lineWidth = 2; context.lineJoin = 'round'; context.beginPath(); curve.forEach((point, i) => (i ? context.lineTo(x(point.x), yRight(point.y)) : context.moveTo(x(point.x), yRight(point.y)))); context.stroke(); }
  else { context.fillStyle = COLOR.ink; context.globalAlpha = .28; data.forEach((value, i) => { if (!Number.isFinite(pay[i])) return; context.beginPath(); context.arc(x(value), yRight(pay[i]), narrow ? 1.6 : 2, 0, Math.PI * 2); context.fill(); }); context.globalAlpha = 1; }
  context.strokeStyle = COLOR.ink; context.lineWidth = 1; context.beginPath(); context.moveTo(pad.left + .5, pad.top); context.lineTo(pad.left + .5, pad.top + plotH + .5); context.lineTo(width - pad.right + .5, pad.top + plotH + .5); context.lineTo(width - pad.right + .5, pad.top); context.stroke();
  context.fillStyle = COLOR.muted; context.textAlign = 'center'; context.textBaseline = 'top'; xTicks.forEach((tick) => context.fillText(num(tick), x(tick), pad.top + plotH + 6));
  context.textAlign = 'left'; context.textBaseline = 'middle'; rightTicks.forEach((tick) => { const y = yRight(tick); context.beginPath(); context.strokeStyle = COLOR.ink; context.moveTo(width - pad.right, y + .5); context.lineTo(width - pad.right + 4, y + .5); context.stroke(); context.fillText(usd(tick), width - pad.right + 7, y); });
  context.fillStyle = COLOR.ink; context.textAlign = 'center'; context.textBaseline = 'bottom'; context.fillText(xTitle, pad.left + plotW / 2, height - 6);
  context.save(); context.translate(narrow ? 11 : 13, pad.top + plotH / 2); context.rotate(-Math.PI / 2); context.textBaseline = 'middle'; context.fillText('Simulated seasons', 0, 0); context.restore();
  context.save(); context.translate(width - (narrow ? 8 : 10), pad.top + plotH / 2); context.rotate(Math.PI / 2); context.textBaseline = 'middle'; context.fillText('Payout (USD)', 0, 0); context.restore();
  return true;
}

/* ---------- result wording ---------- */
const kindNoun = (kind, spec) => `${spec.cap != null && ['call', 'put'].includes(kind) ? 'capped ' : ''}${KIND_NOUN[kind] || kind.replaceAll('_', ' ')}`;
/** "January 2027 call, strike 1,188" — names a priced ticket in a few words. */
function ticketSummary(outcome) {
  const { kind, spec, windows, next } = outcome; const noun = kindNoun(kind, spec);
  const strikes = TWO_STRIKE_KINDS.includes(kind) ? `strikes ${num(spec.strike)} and ${num(next.secondaryStrike)}` : `strike ${num(spec.strike)}`;
  return `${seasonLabel(windows)} ${next.payoffStructure === 'sum_of_monthly_options' ? `monthly ${noun}s added together` : noun}, ${strikes}`;
}
function sentenceFor(outcome, county) {
  const { kind, spec, contractMultiplier, windows, next, paths, probability, expected } = outcome;
  const strong = (text) => node('strong', text); const parts = [];
  const kindWord = indexKindWord(outcome.shared.indexId); const capped = spec.cap != null && ['call', 'put'].includes(kind); const noun = kindNoun(kind, spec);
  const summed = next.payoffStructure === 'sum_of_monthly_options'; const pays = summed ? 'paying' : 'pays'; const owes = summed ? 'owing' : 'owes';
  if (next.payoffStructure === 'monthly_option') parts.push(`A ${monthYear(windows[0])} ${kindWord} ${noun} on ${county} `);
  else if (next.payoffStructure === 'option_on_strip') parts.push(`A ${seasonLabel(windows)} ${kindWord} ${noun} on ${county}, based on the ${windows.length}-month total, `);
  else parts.push(`${capitalize(countWord(windows.length))} separate monthly ${kindWord} ${noun}s on ${county}, ${seasonLabel(windows)}, each `);
  const per = strong(usd(contractMultiplier)); const strike = strong(num(spec.strike));
  if (kind === 'call') parts.push(`${pays} `, per, ' for every degree day above ', strike);
  else if (kind === 'put') parts.push(`${pays} `, per, ' for every degree day below ', strike);
  else if (kind === 'linear') parts.push(`${pays} `, per, ' for every degree day above ', strike, ` and ${owes} the same for every degree day below it`);
  else if (kind === 'call_spread') parts.push(`${pays} `, per, ' for every degree day between ', strike, ' and ', strong(num(spec.high_strike)));
  else if (kind === 'put_spread') parts.push(`${pays} `, per, ' for every degree day between ', strong(num(spec.low_strike)), ' and ', strike);
  else if (kind === 'collar') parts.push(`${pays} `, per, ' for every degree day below ', strike, ` and ${owes} the same for every degree day above `, strong(num(spec.call_strike)));
  if (summed) parts.push(' in its own month');
  if (capped) parts.push(', up to ', strong(usd(spec.cap)));
  const verb = ['linear', 'collar'].includes(kind) ? 'ends with a positive payout' : 'pays out';
  parts.push(summed ? `. Added together, on ${num(paths.ids.length)} simulated ${seasonPlural(windows)} the total ${verb} ` : ` — on ${num(paths.ids.length)} simulated ${seasonPlural(windows)} it ${verb} `, strong(`${pct(probability, 0)} of the time`), ' and is worth about ', strong(usd(expected)), ' on average.');
  const sentence = node('p', undefined, { class: 'sentence' }); parts.forEach((part) => sentence.append(typeof part === 'string' ? document.createTextNode(part) : part)); return sentence;
}
/** A strike outside the simulated range is almost always a units slip (a January strike on a five-month total). Presentation only.
 *  Separate monthly options are struck month by month, so they are checked against a single month's index, not the season total. */
function strikeNote(outcome) {
  const { spec, curveIndex, paths, windows, probability, shared, next } = outcome; if (!Number.isFinite(spec.strike)) return null;
  const perMonth = next.payoffStructure === 'sum_of_monthly_options'; const finite = (perMonth ? paths.values : curveIndex).filter(Number.isFinite); if (!finite.length) return null;
  const low = quantile(finite, .01); const high = quantile(finite, .99); const below = spec.strike < low; const above = spec.strike > high; if (!below && !above) return null;
  const every = (below ? spec.strike < Math.min(...finite) : spec.strike > Math.max(...finite)) ? 'every' : 'nearly every';
  const single = perMonth || windows.length === 1;
  const what = perMonth ? `${monthName(shared.indexId)} ${indexKindWord(shared.indexId)} outcome` : windows.length === 1 ? `${monthYear(windows[0])} ${indexKindWord(shared.indexId)} outcome` : `${seasonLabel(windows, { short: true })} total`;
  const consequence = probability >= .995 ? 'so this contract pays in every simulated season' : probability <= .005 ? 'so this contract never pays' : 'so the strike sits outside nearly every simulated season';
  const check = single ? 'Check that the strike is meant for a single month.' : 'Check that the strike is in the same units as the structure.';
  return node('p', `The strike of ${num(spec.strike)} is ${below ? 'below' : 'above'} ${every} simulated ${what} (about ${rangeText(low, high, num)} degree days), ${consequence}. ${check}`, { class: 'callout callout-info' });
}

/* ---------- page ---------- */
export async function mountContract({ scenario, loadObject, setScenario, pageLink, countyFor }) {
  const county = countyLabel(countyFor(scenario.fips), scenario.fips);
  /* Left: the ticket. */
  const form = node('form', undefined, { class: 'ticket-form', 'aria-label': 'Contract ticket' });
  const windowCell = node('span', 'Loading…'); const yearCell = node('span', 'Loading…');
  const where = node('fieldset'); where.append(node('legend', 'Where and when'));
  /* The valuation date is already in the context strip above; it is not repeated here. */
  where.append(kvTable([['County', county], ['Index', pairLabel(scenario.indexId)], ['Contract window', windowCell], ['Contract year', yearCell]]));
  const changeRow = node('p', undefined, { class: 'link-row' }); changeRow.append(node('a', 'Change county or month on Explore', { href: pageLink('index.html') })); where.append(changeRow);
  const family = node('select', undefined, { id: 'payoff-family' }); FAMILIES.forEach(([value, label]) => { const option = node('option', label, { value }); option.selected = value === scenario.payoffFamily; family.append(option); });
  const structure = node('select', undefined, { id: 'payoff-structure' }); const monthlyOption = node('option', 'Single month', { value: 'monthly_option' }); monthlyOption.selected = scenario.payoffStructure === 'monthly_option'; structure.append(monthlyOption);
  const strike = node('input', undefined, { id: 'strike', type: 'number', inputmode: 'decimal', step: 'any', value: scenario.strike ?? '' });
  const secondStrike = node('input', undefined, { id: 'second-strike', type: 'number', inputmode: 'decimal', step: 'any', value: scenario.secondaryStrike ?? '' });
  const cap = node('input', undefined, { id: 'cap', type: 'number', inputmode: 'decimal', step: 'any', min: '0', value: scenario.cap ?? '', placeholder: 'No cap' });
  const multiplier = node('input', undefined, { id: 'multiplier', type: 'number', inputmode: 'decimal', step: 'any', value: scenario.multiplier ?? '' });
  const load = node('input', undefined, { id: 'assumed-load', type: 'number', inputmode: 'decimal', step: 'any', value: scenario.assumedLoad ?? '', placeholder: 'None' });
  const strikeField = field('Strike (degree days)', strike, 'Loading the reference strike…'); const secondField = field('Second strike (degree days)', secondStrike, SECOND_STRIKE_HINT[scenario.payoffFamily] || SECOND_STRIKE_HINT.spread);
  const multiplierField = field('Payout per degree day (USD)', multiplier, 'Loading the reference payout…'); const capField = field('Cap (USD)', cap, 'Optional. Caps a call or put; spreads and collars ignore it.');
  const payoff = node('fieldset'); payoff.append(node('legend', 'Payoff'), field('Payoff shape', family, 'What the contract pays at the end of the window'), field('Structure', structure, 'One month, or a season built from several months'));
  const strikes = node('div', undefined, { class: 'field-row' }); strikes.append(strikeField, secondField); const amounts = node('div', undefined, { class: 'field-row' }); amounts.append(multiplierField, capField); payoff.append(strikes, amounts);
  const optional = node('fieldset'); optional.append(node('legend', 'Optional'), field('Assumed risk-transfer loading (USD)', load, 'Added to the expected payout as your own assumption. The release assumes none.'));
  const submit = button('Price this contract', { primary: true, type: 'submit' }); const actions = node('div', undefined, { class: 'btn-row' }); actions.append(submit);
  form.append(where, payoff, optional, actions);
  const ticketPanel = node('section', undefined, { class: 'panel' }); ticketPanel.append(node('h2', 'Contract ticket'), form);
  /* Right: the result. */
  const result = node('section', undefined, { class: 'panel stack', 'aria-live': 'polite', 'aria-label': 'What the contract would pay' });
  const status = node('p', undefined, { class: 'status' }); const head = node('div', undefined, { class: 'panel-head' }); head.append(node('h2', 'What it would pay'), status);
  const body = node('div', undefined, { class: 'stack result-body' }); const callout = node('p', undefined, { class: 'callout callout-warn hidden', role: 'alert' });
  body.append(node('p', 'Pricing the ticket on the simulated seasons…', { class: 'muted' }));
  result.append(head, callout, body);
  const layout = node('div', undefined, { class: 'two-col' }); layout.append(ticketPanel, result); replacePanel('.lab-panel', [layout]);

  /* Form behaviour. */
  let declared = null; let quoteRecord = null; let referenceStrike = null;
  const syncSecondStrike = () => { const needed = NEEDS_SECOND_STRIKE.includes(family.value); secondField.classList.toggle('hidden', !needed); secondField.querySelector('.hint').textContent = SECOND_STRIKE_HINT[family.value] || SECOND_STRIKE_HINT.spread; };
  /* The release declares one reference strike, for the single month. A seasonal structure is priced in different units, so the hint must say so. */
  const syncStrikeHint = () => {
    if (!declared) return; const hasReference = Number.isFinite(Number(referenceStrike)); const month = monthName(scenario.indexId) || 'single-month';
    const { windows } = windowFor(declared, structure.value); const season = seasonLabel(windows, { short: true }); let text;
    if (structure.value === 'option_on_strip' && windows.length > 1) text = `Strikes for this structure are in degree days of the ${season} total, roughly ${countWord(windows.length)} times a single month.${hasReference ? ` The ${month} reference strike of ${num(referenceStrike, 1)} does not apply.` : ''}`;
    else if (structure.value === 'sum_of_monthly_options' && windows.length > 1) text = `The same strike applies to each month’s own degree days, ${season}.${hasReference ? ` The ${month} reference strike of ${num(referenceStrike, 1)} fits ${month} only; the other months run differently.` : ''}`;
    else text = hasReference ? `The release’s reference strike is ${num(referenceStrike, 1)} degree days` : 'The release publishes no reference strike';
    strikeField.querySelector('.hint').textContent = text;
  };
  const syncWindow = () => { if (!declared) return; const { windows, start, end } = windowFor(declared, structure.value); windowCell.textContent = windows.length > 1 ? `${dateRange(start, end)} (${windows.length} months)` : dateRange(start, end); syncStrikeHint(); };
  family.addEventListener('change', syncSecondStrike); structure.addEventListener('change', syncWindow); syncSecondStrike();
  function applyQuote(record) {
    quoteRecord = record; const ticket = record.payload || {}; declared = ticket.option_contract || {}; const reference = declared.payoff || {}; const selected = ticket.selection_asof || {};
    const fresh = scenario.strike == null && scenario.multiplier == null;
    if (fresh && reference.kind) family.value = reference.kind;
    if (scenario.strike == null && Number.isFinite(Number(reference.strike))) strike.value = displayStrike(reference.strike);
    if (scenario.multiplier == null && Number.isFinite(Number(reference.payout_usd_per_degree_day))) multiplier.value = reference.payout_usd_per_degree_day;
    referenceStrike = Number.isFinite(Number(reference.strike)) ? Number(reference.strike) : null;
    multiplierField.querySelector('.hint').textContent = Number.isFinite(Number(reference.payout_usd_per_degree_day)) ? `The reference ticket pays ${usd(reference.payout_usd_per_degree_day)} per degree day` : 'Dollars paid for each degree day in the money';
    const single = windowFor(declared, 'monthly_option'); monthlyOption.textContent = `Single month — ${seasonLabel(single.windows)}`;
    (declared.seasonal_structures || []).forEach((item) => { const season = seasonLabel(item.member_windows || [], { short: true }); const label = STRUCTURE_LABEL[item.aggregation] ? STRUCTURE_LABEL[item.aggregation](season) : `${item.label} — ${season}`; const option = node('option', label, { value: item.aggregation }); option.selected = item.aggregation === scenario.payoffStructure; structure.append(option); });
    if (![...structure.options].some((option) => option.selected)) monthlyOption.selected = true;
    yearCell.textContent = selected.contract_year ?? declared.contract_year ?? NA;
    syncSecondStrike(); syncWindow();
  }

  /* Rendering. */
  let lastOutcome = null; let redraw = null;
  const controls = { strike, second: secondStrike, multiplier, cap, load, structure };
  const clearFieldErrors = () => { form.querySelectorAll('.field-error').forEach((item) => item.remove()); form.querySelectorAll('[aria-invalid]').forEach((item) => item.removeAttribute('aria-invalid')); };
  const showError = (error, { fromUser = true } = {}) => {
    const { text, field: fieldKey } = friendlyError(error); const summary = lastOutcome ? ticketSummary(lastOutcome) : null;
    /* The figures, links and export stay live for the last priced ticket (V2 ordering: the URL already carries the new one), so say which ticket is on screen. */
    callout.textContent = summary ? `${text} The figures, links and export below are still for the last ticket that could be priced (${summary}).` : text; callout.classList.remove('hidden');
    status.textContent = summary ? `Showing the last ticket that could be priced: ${summary}.` : ''; body.classList.toggle('is-stale', Boolean(lastOutcome));
    if (!lastOutcome) body.replaceChildren(node('p', 'Fill in the contract ticket and choose Price this contract. The payout, chart and hedge figures will appear here.', { class: 'muted' }));
    /* Say it at the field too: on a phone the result panel sits below the ticket. */
    clearFieldErrors(); const control = fieldKey ? controls[fieldKey] : null;
    if (control) { control.setAttribute('aria-invalid', 'true'); control.closest('.field')?.append(node('span', text, { class: 'field-error' })); if (fromUser) control.focus(); }
    else if (fromUser) callout.scrollIntoView({ block: 'nearest' });
  };
  function renderOutcome(outcome) {
    const { ticket, declared: contract, chosenStructure, paths, contractMultiplier, spec, kind, payoff: values, expected, residual, hedgeRatio, hedgeFailure, stationEntity, enteredLoad, loadedExpected, probability, isPayoffFunction, curveIndex, shared, windows, next, payoffKernel } = outcome;
    const price = ticket.price || {}; const selected = ticket.selection_asof || {}; const stationName = stationEntity ? stationCity(stationEntity) : null;
    const single = windows.length === 1; const seasonWord = seasonPlural(windows); const seasonOne = single ? monthName(windows[0].pair) : `${monthName(windows[0].pair)}–${monthName(windows.at(-1).pair)} season`;
    callout.classList.add('hidden'); body.classList.remove('is-stale'); status.textContent = `Priced on ${num(paths.ids.length)} simulated ${seasonWord}.`;
    const p5 = quantile(values, .05); const p95 = quantile(values, .95); const median = quantile(values, .5); const r5 = residual ? quantile(residual, .05) : null; const r95 = residual ? quantile(residual, .95) : null;
    const metricTiles = tiles([
      tile('Expected payout', usd(expected), `average over all simulated ${seasonWord}`),
      tile('Chance of paying out', pct(probability, 0), `share of simulated ${seasonWord} with a positive payout`),
      tile('Typical payout range', rangeText(p5, p95, usd), `9 in 10 simulated ${seasonWord} land in this range · median ${usd(median)}`, { small: true }),
      tile(stationName ? `After hedging with ${stationName}` : 'After hedging with a listed station', residual ? rangeText(r5, r95, usd) : NA, residual ? `9 in 10 simulated ${seasonWord} land in this range after hedging with the ${stationName} swap` : `Unavailable: ${hedgeFailure || 'no station hedge'}.`, { small: true, na: !residual }),
      tile('Hedge ratio', ratio(hedgeRatio, 2), hedgeRatio != null ? `size of the ${stationName} swap, at the same ${usd(contractMultiplier)} per degree day, that best offsets one of these contracts` : `Unavailable: ${hedgeFailure || 'no station hedge'}.`, { na: hedgeRatio == null }),
      tile('Simulated seasons', num(paths.ids.length), `each a simulated ${seasonOne}; the same ones are used for the county and the station`),
    ]);
    /* Chart. */
    const indexPhrase = single ? `${monthYear(windows[0])} ${pairKindWords(shared.indexId)}` : `${seasonLabel(windows, { short: true })} ${pairKindWords(shared.indexId)}`;
    const xTitle = single ? indexPhrase : `${indexPhrase}, ${windows.length}-month total`; const captionIndex = `the ${xTitle}`;
    const twoStrikes = TWO_STRIKE_KINDS.includes(kind);
    const figure = node('figure'); const canvas = node('canvas', undefined, { 'aria-label': `Distribution of the simulated ${xTitle}, with the contract payoff overlaid. ${isPayoffFunction ? `The ${twoStrikes ? 'two strikes are' : 'strike is'} marked.` : 'Each month is struck on its own degree days, so the strike is not marked on this season-total axis.'}` });
    const key = node('p', undefined, { class: 'chart-key' });
    const keyItem = (swatchClass, text) => { const item = node('span'); item.append(node('i', undefined, { class: swatchClass }), document.createTextNode(text)); return item; };
    const marksStrike = isPayoffFunction;
    key.append(keyItem('bar', 'How often each index level occurs'), keyItem(isPayoffFunction ? 'line' : 'dot', isPayoffFunction ? 'What the contract pays at that level' : 'Total payout of each simulated season'), ...(marksStrike ? [keyItem('dash', twoStrikes ? 'Strikes' : 'Strike')] : []));
    const caption = node('figcaption', `Bars: how many of the ${num(paths.ids.length)} simulated seasons fall at each level of ${captionIndex} (left axis). ${isPayoffFunction ? 'Line: what this contract pays at each level (right axis, USD).' : 'Dots: the total payout of each simulated season from the separate monthly options, against that season’s index total (right axis, USD); with this structure the payout is not one curve.'} ${marksStrike ? (twoStrikes ? 'The dashed lines mark the two strikes.' : 'The dashed line marks the strike.') : 'Each month is struck on its own degree days, so the strike is not a level on this season-total axis and is not marked.'}`);
    figure.append(canvas, key, caption);
    const markers = isPayoffFunction ? [{ value: spec.strike, label: `Strike ${num(spec.strike)}` }] : [];
    if (twoStrikes && isPayoffFunction) markers.push({ value: Number(next.secondaryStrike), label: `Second strike ${num(next.secondaryStrike)}` });
    const draw = () => {
      let curve = null;
      if (isPayoffFunction) { const finite = curveIndex.filter(Number.isFinite); const lo = Math.min(...finite, ...markers.map((m) => m.value)); const hi = Math.max(...finite, ...markers.map((m) => m.value)); const grid = Array.from({ length: 241 }, (_, i) => lo + (hi - lo) * i / 240); try { const ys = payoffKernel.payoff(kind, grid, spec); curve = grid.map((value, i) => ({ x: value, y: ys[i] })); } catch { curve = curveIndex.map((value, i) => ({ x: value, y: values[i] })).sort((a, b) => a.x - b.x); } }
      const drawn = drawContractChart(canvas, { index: curveIndex, payoff: values, curve, markers, xTitle });
      if (!drawn) figure.replaceChildren(node('p', 'The chart is unavailable for this ticket.', { class: 'muted' }));
    };
    /* Three separate numbers. */
    const referencePhysical = price.physical?.status === 'available' && price.physical?.amount != null ? `The release’s reference ticket is worth ${usd(price.physical.amount)}.` : statusText(price.physical?.reason || price.physical?.status);
    const numbers = dataTable(['Number', 'Amount', 'What it means'], [
      ['Expected payout', usd(expected), `Average payout across the ${num(paths.ids.length)} simulated ${seasonWord}, using real-world weather odds rather than a market’s. ${referencePhysical}`],
      ['Assumed risk-transfer loading', enteredLoad == null ? NA : usd(enteredLoad), enteredLoad == null ? statusText(price.model_load?.reason || price.model_load?.status) : `Your assumption, not the release’s. Expected payout plus loading: ${usd(loadedExpected)}.`],
      ['Market price', price.market?.amount != null ? usd(price.market.amount) : NA, statusText(price.market?.reason || price.market?.status)],
    ], { numeric: [1] });
    const numbersSection = node('div'); numbersSection.append(node('h3', 'Three separate numbers'), node('p', 'Reported apart, so none of them is mistaken for a quote.', { class: 'status' }), numbers);
    /* Actions. The export shape is unchanged from V2. */
    const exportButton = button('Download this ticket (JSON)', { quiet: true });
    exportButton.addEventListener('click', () => downloadDecision({ schema_version: '2.0', release_id: scenario.releaseId, ticket_id: outcome.quoteRecord.object_id, scenario_set_id: paths.scenarioSetId, contract_spec: { ...shared, payoff_kind: kind, payoff_spec: spec, hedge_ratio: hedgeRatio, selected_station_entity_id: stationEntity || null }, result: { physical_expected_payout: expected, positive_payout_probability: probability, physical_distribution: values, station_hedged_residual_distribution: residual, customer_entered_load: enteredLoad, loaded_expected_payout: loadedExpected } }, 'weather-basis-contract-decision.json'));
    const actionRow = node('div', undefined, { class: 'btn-row' });
    actionRow.append(linkButton('Compare counties', pageLink('compare.html', shared)), linkButton('Add this contract to a portfolio', pageLink('portfolio.html', shared), { primary: true }), exportButton);
    const roomLine = node('p', undefined, { class: 'status result-links' }); roomLine.append(document.createTextNode('Or '), node('a', 'open it in the Scenario Room', { href: `${pageLink('portfolio.html', shared)}#scenario-room` }), document.createTextNode(' to stress it alongside other contracts.'));
    const provenance = envelopeProvenance(outcome.quoteRecord, [['Simulated paths', paths.scenarioSetId], ['Ticket', outcome.quoteRecord.object_id], ['Contract definition', ticket.contract_definition_id], ['Contract specification', contract.contract_spec_id], ['Structure', chosenStructure?.structure_id], ['Selected station', stationEntity], ['Station name', stationEntity ? stationLabel(stationEntity) : null], ['Contract window', selected.contract_window_id], ['Observation cutoff', selected.observation_cutoff], ['Metadata cutoff', selected.metadata_cutoff], ['Payout per degree day', contractMultiplier], ['Payoff kind', kind], ['Payoff kernel', 'js/kernels/portfolio.js']]);
    body.replaceChildren(...[strikeNote(outcome), sentenceFor(outcome, county), metricTiles, figure, numbersSection, actionRow, roomLine, provenance].filter(Boolean));
    draw(); redraw = draw;
  }
  let resizeTimer = null; window.addEventListener('resize', () => { if (!redraw) return; clearTimeout(resizeTimer); resizeTimer = setTimeout(() => redraw && redraw(), 150); });

  /* Submit: same state transitions as V2 (setScenario first, then price). */
  async function run(mode, { fromUser = true } = {}) {
    const next = { payoffFamily: family.value, payoffStructure: structure.value, strike: strike.value || null, secondaryStrike: secondStrike.value || null, cap: cap.value || null, multiplier: multiplier.value || null, assumedLoad: load.value || null };
    setScenario(next, mode); clearFieldErrors();
    /* A spread or collar with an empty second strike cannot be priced; say so before calling the kernel (an empty box would otherwise read as a strike of zero). */
    if (NEEDS_SECOND_STRIKE.includes(next.payoffFamily) && secondStrike.value.trim() === '') { showError(new Error('This payoff family requires a second strike.'), { fromUser }); return; }
    status.textContent = 'Pricing on the simulated seasons…'; result.setAttribute('aria-busy', 'true'); submit.disabled = true;
    try { const outcome = await calculate(next, load.value, { scenario, loadObject, setScenario }); lastOutcome = outcome; renderOutcome(outcome); }
    catch (error) { showError(error, { fromUser }); }
    finally { result.removeAttribute('aria-busy'); submit.disabled = false; }
  }
  form.addEventListener('submit', (event) => { event.preventDefault(); run(); });

  /* Open with the reference ticket already priced. */
  try { applyQuote(await loadObject(`quote:${scenario.fips}:${scenario.indexId}`)); }
  catch (error) { windowCell.textContent = NA; yearCell.textContent = NA; strikeField.querySelector('.hint').textContent = 'No reference strike is available for this county and month'; multiplierField.querySelector('.hint').textContent = 'Dollars paid for each degree day in the money'; }
  await run('replaceState', { fromUser: false });
}
