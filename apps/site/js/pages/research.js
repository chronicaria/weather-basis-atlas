/** Research library: how the atlas is built, and what it can and cannot claim.
 *  Presentation only. Every record is loaded with `loadObject`, the `?record=`
 *  URL state goes through `scenario.researchRecord` + `setScenario`, and the
 *  raw payload is always reachable under "All reported fields". Identifiers
 *  (digests, release and object ids) are swept out of the visible fields and
 *  into the collapsed provenance block so a result stays reproducible. */
import { node, replacePanel } from './render.js';
import {
  NA, STATIONS, countyLabel, dataTable, dateShort, humanize, km, kvTable, linkButton, num, pairLabel, pct, provenanceBlock, pts, rangeText, releaseLabel, seasonRange, signed, stationCity, stationLabel, statusText, tile, tiles, usd,
} from './format.js';

const REPO_URL = 'https://github.com/chronicaria/weather-basis-atlas';
const ABOUT_KEY = 'about';
const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
/* The Nebraska case: five counties, two indexes. Public county objects exist for each pair. */
const NEBRASKA_FIPS = ['31055', '31109', '31079', '31111', '31157'];
const NEBRASKA_PAIRS = ['HDD-01', 'CDD-07'];
const POOR_HEDGE_FIPS = '31157';

/* ---------- record catalogue: titles, table-of-contents labels, grouping ---------- */
const GROUP_ORDER = ['Start here', 'Registered experiments', 'Case studies', 'How the evidence is checked', 'Provenance', 'More records'];
const RECORDS = {
  [ABOUT_KEY]: { title: 'About the atlas', toc: 'About the atlas', group: 'Start here' },
  'research:glossary': { title: 'Glossary', toc: 'Glossary', group: 'Start here' },
  'research:limitations': { title: 'Limits of this release', toc: 'Limits of this release', group: 'Start here' },
  'research:source_support': { title: 'Where the temperature data come from', toc: 'Data sources', group: 'Start here' },
  'research:data': { title: 'The fixed copy of the data', toc: 'Fixed data copy', group: 'Start here' },
  'research:method': { title: 'How the experiments were designed', toc: 'Experiment design', group: 'Registered experiments' },
  'research:r01': { title: 'R01 · Does choosing a station by past performance beat the nearest one?', toc: 'R01 · Past performance vs nearest', group: 'Registered experiments' },
  'research:r02': { title: 'R02 · Do small station baskets help in Nebraska?', toc: 'R02 · Station baskets', group: 'Registered experiments' },
  'research:r03': { title: 'R03 · Is a joint book better than separate hedges?', toc: 'R03 · Joint book', group: 'Registered experiments' },
  'research:r04': { title: 'R04 · Which weather generator is better calibrated?', toc: 'R04 · Weather generator', group: 'Registered experiments' },
  'research:r05': { title: 'R05 · Where is basis risk irreducible?', toc: 'R05 · Irreducible basis risk', group: 'Registered experiments' },
  'research:nebraska': { title: 'Nebraska case study', toc: 'Nebraska', group: 'Case studies' },
  'research:next_station': { title: 'Next-station pilot', toc: 'Next-station pilot', group: 'Case studies' },
  'research:holdout': { title: 'Which seasons have already been used', toc: 'Seasons already used', group: 'How the evidence is checked' },
  'research:validation': { title: 'How the evidence fits together', toc: 'How it fits together', group: 'How the evidence is checked' },
  'research:performance': { title: 'How long the generator comparison took to run', toc: 'Time and memory used', group: 'How the evidence is checked' },
  'research:releases': { title: 'This release', toc: 'This release', group: 'Provenance' },
};
const recordMeta = (key) => RECORDS[key] || { title: humanize(key), toc: humanize(key), group: 'More records' };

/* ---------- plain-language maps for machine codes ---------- */
const REASON_TEXT = {
  frozen_research_vintage_not_settlement_feed: 'These are fixed public research inputs, not a live settlement feed.',
  historical_case_predictive_books_published_separately: 'This is a historical case. The forward-looking Nebraska portfolio books are published separately in the Portfolio Lab.',
  retrospective_historical_evidence: 'Retrospective historical evidence: it describes what would have happened on matched seasons, not what will happen.',
  bounded_or_retrospective_evidence: 'Retrospective, bounded evidence: it describes matched history within a stated scope and makes no forward claim.',
  not_final_national_or_predictive_validation: 'A bounded study, not the national validation and not a predictive claim.',
  two_scoreable_origins_inconclusive: 'Only two decision points could be scored, so the comparison is inconclusive.',
  missing_heldout_common_daily_support: 'No held-out daily record was available for every series at this decision point.',
};
const DISPOSITION_TEXT = {
  representative_improvement_needs_confirmation: 'Improvement seen; it still needs confirming on seasons set aside in advance',
  inconclusive_or_retain_simple: 'Inconclusive; keep the simple nearest-station choice',
  retain_separate_or_inconclusive: 'Inconclusive; keep separate hedges',
  observed_joint_improvement_needs_B11_confirmation: 'Joint book looked better on observed history; needs confirming on shared simulated scenarios',
  promote: 'Kept as a research feature, not as a trading recommendation',
  retain_research: 'Kept as research only',
  inconclusive: 'Inconclusive',
  stop_missing_evidence: 'Stopped: not enough evidence',
  inconclusive_small_registered_origin_count: 'Inconclusive because too few decision points were registered; the two-stage daily generator is kept for daily and strip work, and the common-year trend stays the tested monthly baseline',
  'descriptive sensitivity only': 'A descriptive screen only; the national rule waits for the rebuilt national inputs',
};
/** Short forms of the same readings, for a table cell where the full sentence would not fit. */
const DISPOSITION_SHORT = {
  representative_improvement_needs_confirmation: 'Basket hedged better',
  inconclusive_or_retain_simple: 'Inconclusive',
  retain_separate_or_inconclusive: 'Inconclusive',
  observed_joint_improvement_needs_B11_confirmation: 'Joint book hedged better',
};
/** Sentences the release wrote for itself, rewritten for a reader outside the project. */
const INTERPRETATION_TEXT = {
  'Includes all five locations and retains inconclusive outcomes.':
    'All five counties are reported, including the ones where the comparison came out inconclusive. Nothing was dropped for looking unhelpful.',
};
/* Registered limits, rewritten for a reader who has not seen the codebase. The recorded wording stays under "All reported fields". */
const LIMIT_TEXT = {
  'County nClimGrid and GHCN proxy indexes are frozen public research inputs, not official contract settlement records.':
    'The county and station indexes are rebuilt from fixed public NOAA temperature records. They are research reconstructions, not the official values a contract would settle on.',
  'Historical availability is retrospective because issue-time availability and revisions are unknown.':
    'Every historical figure is computed from today\'s revised data. What a station\'s record actually looked like on a past decision date, and how it was later revised, is not known.',
  'R02/R03 are five-county observed-index studies; R05 is a bounded national sensitivity screen.':
    'The station-basket and joint-book experiments cover five Nebraska counties only. The irreducible-risk experiment is a national screen with a limited set of settings, not a full national test.',
  'R04 has two registered origins, so its generator selection is inconclusive rather than complexity proof.':
    'The weather-generator comparison could be scored at only two decision points, so it does not establish which generator is better.',
  'Stress paths are non-probabilistic and cannot produce predictive expected shortfall.':
    'The stress paths shown elsewhere on the site are illustrative scenarios with no probabilities attached, so no forward-looking expected shortfall can be read from them.',
};
/* The three candidate weather generators, by the names the release uses. */
const GENERATOR_TEXT = {
  common_year_trend: 'Common-year trend', r2j: 'Two-stage daily generator (R2j)', rank_coupled_monthly: 'Rank-coupled monthly',
  'r2j-raw-residual-before-ar-v1': 'The two-stage daily generator (R2j)',
};
const GENERATOR_PHRASE = { common_year_trend: 'common-year trend', r2j: 'two-stage daily generator (R2j)', rank_coupled_monthly: 'rank-coupled monthly generator' };
/** Column headings: the same three generators, short enough for a table header. */
const GENERATOR_SHORT = { common_year_trend: 'Common-year trend', r2j: 'Two-stage daily', rank_coupled_monthly: 'Rank-coupled monthly' };
/* How the release describes the shape of its own evidence, in words. */
const TOPOLOGY_TEXT = {
  'R04 reports mean CRPS and energy score separately for common-year and R2j candidates.': 'The generator comparison scores each index on its own, and then scores a whole simulated year across all of them at once, keeping the two scores separate for every candidate generator.',
  'R04 uses common date-consistent columns over seven counties and 18 stations; it does not treat paths as independent observed years.': 'The generator comparison lines up the same dates across seven counties and eighteen stations, so a simulated path is judged as one joined-up year. It is never counted as an extra observed year.',
  'R02 sparse baskets, R03 joint observed-index book, R05 sensitivity screen, and the Nebraska case remain separate evidence tiers.': 'The basket study, the joint-book study, the national screen and the Nebraska case stand on their own. None of them inherits another\'s conclusion, and none is strong enough to support a national claim by itself.',
};
const POLICY_TEXT = { 'sealed bundle is built only from pinned public projections': 'The bundle is built only from public inputs, each pinned to one exact version, and sealed so it cannot change afterwards.' };
/* Registered decision rules for the next-station pilot, in plain words. */
const RULE_TEXT = {
  promote_rule: ['Keep as a research feature', 'The station chosen on training data must be scored at enough paired decision points, and the lower end of its 95% band must stay above zero for both measures of risk. Even then the result is a research feature, never a recommendation to trade.'],
  retain_research_rule: ['Keep as research only', 'The chosen addition helps on both measures, but the bar above is not cleared.'],
  inconclusive_rule: ['Inconclusive', 'At least one comparison could be scored, but neither rule above is met.'],
  stop_missing_evidence_rule: ['Stop for missing evidence', 'No comparison reaches the minimum number of paired decision points.'],
};
/* Held-out ledger wording. */
const LEDGER_TEXT = {
  'consumed exploratory/development evidence': 'Already used while developing the studies',
  'not yet observed': 'Has not happened yet',
  'retrospective; it is not an untouched final holdout': 'Looking backwards only: these years cannot serve as an untouched final test.',
  'requires a preregistered evaluation before a prospective claim': 'A forward-looking claim would need a test registered in advance of these seasons.',
  'future origins': 'Future decision points',
};
const STATUS_WORD = { complete: 'Yes', unavailable: 'No', executed: 'Executed', available: 'Available', partial: 'Partial' };
const MARKET_TEXT = {
  absent_paid_or_registered_history: 'No paid or registered market price history is used, so nothing on this site is a quote.',
  absent_authorized_settlement_history: 'No authorised exchange settlement history is used; the indexes are research reconstructions from public observations.',
};
const SOURCE_NAMES = { 'county-tavg-v1': 'County mean temperature', 'county-tmax-v1': 'County daily maximum', 'county-tmin-v1': 'County daily minimum', 'station-tmean-v1': 'Station mean temperature' };
const VARIABLE_TEXT = { TAVG: 'Daily mean temperature', TMAX: 'Daily maximum temperature', TMIN: 'Daily minimum temperature', TMEAN: 'Daily mean of maximum and minimum' };
const GLOSSARY_TERMS = { replication_HE: 'Replication hedge effectiveness', economic_loss_and_ES: 'Economic loss and expected shortfall', current_decision: 'Current decision', historical_policy: 'Historical policy', physical_indication: 'Physical indication', aligned_scenarios: 'Aligned scenarios' };
/* Plain readings of the release's registered definitions, written for the public. The exact registered wording stays available below them. */
const GLOSSARY_PLAIN = {
  replication_HE: 'How much of a county\'s year-to-year index variation a station hedge would have removed, scored on exactly the seasons both records share. 100% is a perfect match; it cannot be computed when the county index barely varies.',
  economic_loss_and_ES: 'Dollar losses and expected shortfall are computed on the same simulated seasons as the contract. They are money amounts, not effectiveness percentages, and losses from separate hedges cannot simply be added together.',
  current_decision: 'A station choice made for the coming contract window using only information that was available before that window began.',
  historical_policy: 'The same choose-ahead rule applied at each past decision point, then scored only once that season\'s outcome was known.',
  physical_indication: 'An expected value computed from simulated weather alone. It carries no risk margin and no market price, so it is not a quote.',
  aligned_scenarios: 'Simulated seasons that share the same scenario set and scenario numbers, so a county value and a station value always come from the same simulated year. Separately sorted lists are for display only and do not describe a portfolio.',
};
const ADMISSION_TEXT = { research_proxy_pending_origin_qc: 'Research proxy; awaiting per-decision-point quality checks' };
const ROLE_TEXT = { nebraska: 'Nebraska research proxy', listed: 'Listed station' };
const STRATEGY_TEXT = { baseline: 'The five-county book on its own', fixed_combo_omaha_scottsbluff: 'Always add Omaha and Scottsbluff', training_selected_one_addition: 'Add whichever station the training data picks' };
const OBJECTIVE_TEXT = { es: 'Expected shortfall (ES90)', variance: 'Variance' };
const PROTOCOL_TEXT = {
  nearest_eligible: 'The nearest listed station', prior_best: 'The station with the best past performance (the prior-best rule)',
  'exact paired seasons': 'Exactly the same historical seasons for both stations', 'chronological outer origin/season': 'Each historical decision point and its season',
  registered_before_reconstruction: 'Registered before the data were rebuilt', 'corrected paired national evaluation': 'Every county and month in the atlas, evaluated in pairs',
  'source protocol registered': 'Registered before the data were rebuilt',
  'D06 replication-MSE HE': 'Hedge effectiveness, measured by how much of the county\'s year-to-year variation the station reproduces',
  'corrected prior-score selection against nearest on matched seasons': 'The prior-best rule against the nearest listed station, on the seasons both records share',
  'prior-only sparse basket': 'A small basket of stations chosen using only earlier seasons',
  'five Nebraska county/station mappings; actual annual index panels': 'Five Nebraska counties and their local airports, scored on the actual yearly index values',
  '20 chronological origins per reported place/pair': 'Twenty decision points in date order for each place and month',
  'same observed-index book and five-station total constraint; not predictive common-scenario evidence': 'The same observed-history book and the same five-station limit on both sides; this is not evidence from shared simulated scenarios',
  'chronological five-county observed-index book; same maximum five-station total constraint; not a B11 predictive common-scenario result': 'A five-county book scored on observed history in date order, with at most five stations either way. It is not the forward-looking comparison on shared simulated scenarios.',
  'bounded national sensitivity screen, not B24 national validation': 'A national screen across a limited set of settings, not the full national validation.',
  'HDD-01 and CDD-07; local station baseline versus prior-only sparse basket': 'January heating degree days and July cooling degree days, comparing the local airport with a small basket chosen from earlier seasons only',
};
const LABELS = {
  ci95: '95% interval', paired_mean_ci95: 'Mean paired change, 95% interval', mean_paired_squared_loss_change: 'Mean paired change in squared loss', es: 'Expected shortfall', mse: 'Mean squared error', n: 'Seasons', origins: 'Decision points', origin: 'Decision point', pair: 'Index', place: 'Place', disposition: 'Reading', top_basket_frequency: 'Most frequent basket', basket: 'Basket', nearest: 'Nearest station', joint: 'Joint book', separate: 'Separate hedges', protocol_id: 'Protocol', experiment: 'Experiment', experiment_id: 'Experiment', scope: 'Scope', limitations: 'Limits', interpretation: 'Reading', results: 'Results', registered_experiment: 'Registered experiment', classification_counts: 'Classification counts', settings: 'Screening settings', positive_in_screen: 'Positive in screen', robustly_difficult: 'Robustly difficult', ambiguous: 'Ambiguous', report: 'Report', rows: 'Decision points', summary: 'Summary', mean_scores: 'Mean scores', n_registered_origins: 'Registered decision points', n_scoreable_origins: 'Scoreable decision points', common_year_trend: 'Common-year trend', r2j: 'R2j', rank_coupled_monthly: 'Rank-coupled monthly', energy_score: 'Energy score', mean_crps: 'Mean CRPS', sum_crps: 'Total CRPS', per_column_crps: 'CRPS by column', columns: 'Columns', fit_cutoff: 'Fit cut-off', peak_rss_bytes: 'Peak memory', runtime_seconds: 'Runtime', scoreability: 'Scored', status: 'Status', training_vectors: 'Training vectors', files: 'Files', pairs: 'Indexes', producer: 'Producer', prior_artifact_status: 'Earlier run', reason: 'Reason', matched_table_sha256: 'Matched table digest', protocol: 'Protocol', baseline: 'Baseline', challenger: 'Challenger', common_support: 'Compared on', equivalence_bands: 'Practical-equivalence bands', id: 'Identifier', inference_unit: 'Unit of evidence', metric: 'Metric', question: 'Question', county_window_records: 'County-and-window records', evaluable: 'Evaluable', fraction_of_evaluable: 'Share of evaluable', prior_best_exceeds_nearest: 'Best prior score beat nearest', unavailable: 'Not evaluable', case: 'Case', mapping: 'County to station map', county: 'County', fips: 'FIPS', station: 'Station', adjudication: 'Adjudication rules', admission_table: 'Admission table', case_page_payload: 'Case page', cluster_unit: 'Cluster unit', consumed_development_years: 'Development years used', cost_table: 'Cost table', objective_summary: 'Objective summary', supersedes: 'Supersedes', uncertainty: 'Uncertainty', uncertainty_disclosure: 'Uncertainty disclosure', variance_vs_es_disagreement: 'Variance versus expected-shortfall disagreement', inconclusive_rule: 'Inconclusive', minimum_paired_origins: 'Minimum paired decision points', promote_rule: 'Promote', retain_research_rule: 'Keep as research', stop_missing_evidence_rule: 'Stop for missing evidence', admission_status: 'Admission status', availability_disclosure: 'Availability', elevation_m: 'Elevation (m)', latitude: 'Latitude', longitude: 'Longitude', name: 'Name', registry_role: 'Role', source_operational: 'Source', source_artifact_id: 'Source artifact', source_record_present: 'Source record present', source_retrieved_at_utc: 'Retrieved (UTC)', source_sha256: 'Source digest', source_url: 'Source URL', station_id: 'Station', baseline_scored_origins: 'Baseline scored points', mean_deterministic_cost: 'Mean held-out cost', missing_heldout_outcomes: 'Missing held-out outcomes', objective: 'Objective', paired_gain: 'Paired gain', gain: 'Gain', paired_origins: 'Paired decision points', registered_origins: 'Registered decision points', sensitivity: 'Sensitivity', strategy: 'Strategy', strategy_scored_origins: 'Strategy scored points', common_scored_origins: 'Commonly scored points', different_addition_origins: 'Points where they differ', same_addition_origins: 'Points where they agree', per_origin: 'By decision point', es_addition: 'Addition by expected shortfall', variance_addition: 'Addition by variance', method: 'Method', note: 'Note', resamples: 'Resamples', seed: 'Seed', artifact_id: 'Artifact', station_map: 'Station map', access_ledger: 'Access ledger', period: 'Period', topology: 'Structure', marginal: 'Marginal distributions', dependence: 'Dependence between series', downstream: 'Downstream studies', r04_origins: 'R04 decision points', common_year_mean_crps: 'Common-year mean CRPS', r2j_mean_crps: 'R2j mean CRPS', unavailable_reason: 'Why unavailable', meaning: 'Meaning', r04_producer: 'R04 producer', market_status: 'Market data', settlement_status: 'Settlement data', sources: 'Sources', vintage_id: 'Data vintage', vintage_sha256: 'Vintage digest', aggregation_order: 'Aggregation', coherent_through: 'Coherent through', coverage_end: 'Coverage end', coverage_start: 'Coverage start', historical_availability: 'Historical availability', location_type: 'Location type', support_id: 'Source', unsupported_reason: 'What it cannot be used for', variable: 'Variable', terms: 'Terms', term: 'Term', definition: 'Definition', canonical_index: 'Index definition', items: 'Items', release_lock: 'Release lock', release_policy: 'Release policy', schema_version: 'Schema version', source_artifact_ids: 'Source artifacts', verified_bundle_inventory: 'Bundle inventory', nebraska_case: 'Nebraska case', locations: 'Locations', policy: 'Policy tested', selection: 'Selection rule', unit_of_inference: 'Unit of evidence', comparison: 'Comparison', selected_generator: 'Selected generator', r01: 'R01 · Station choice', r02: 'R02 · Station baskets', r03: 'R03 · Joint book', r04: 'R04 · Weather generator', r05: 'R05 · Irreducible basis risk', market: 'Market', settlement: 'Settlement', row: 'Row', item: 'Item',
};

/* ---------- small formatters ---------- */
const finite = (value) => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
const isIdentifier = (text) => /^(sha256|release|object|decision|candidate-contract|source-group|analysis|selection|scenario-set):/i.test(text) || /[a-f0-9]{24,}/i.test(text);
const isStation = (text) => /^USW\d{8}$/.test(String(text || ''));
const isPair = (text) => /^(HDD|CDD)-\d{2}$/.test(String(text || ''));
function bytesText(value) { if (!finite(value)) return NA; const mb = Number(value) / 1048576; return mb >= 1024 ? `${num(mb / 1024, 2)} GB` : `${num(mb)} MB`; }
function secondsText(value) { return finite(value) ? `${num(value, 1)} s` : NA; }
function monthText(value) { const match = /^(\d{4})-(\d{2})$/.exec(String(value || '')); if (!match) return value ? String(value) : NA; return `${MONTHS_SHORT[Number(match[2]) - 1]} ${match[1]}`; }
/** Values that round to nothing must not print as a negative zero ("−$0"). */
const snap = (value, step) => (finite(value) && Math.abs(Number(value)) < step ? 0 : value);
const money = (value) => usd(snap(value, 0.5));
const count = (value, digits = 0) => num(snap(value, 0.5 * 10 ** -digits), digits);
const signedCount = (value, digits = 0) => signed(snap(value, 0.5 * 10 ** -digits), digits);
function intervalText(pair, format = (v) => count(v)) { if (!Array.isArray(pair) || pair.length < 2) return NA; return rangeText(pair[0], pair[1], format); }
function listText(items) { const list = items.filter(Boolean); if (list.length <= 1) return list.join(''); return `${list.slice(0, -1).join(', ')} and ${list.at(-1)}`; }
function stationSet(text) { return listText(String(text).split('|').map((id) => stationCity(id))); }
function dispositionText(value) { if (value == null || value === '') return NA; const text = String(value); const head = text.split(';')[0].trim(); return DISPOSITION_TEXT[text] || DISPOSITION_TEXT[head] || humanize(text); }
function dispositionShort(value) { if (value == null || value === '') return NA; return DISPOSITION_SHORT[String(value)] || dispositionText(value); }
function interpretationText(value) { if (value == null || value === '') return NA; const text = String(value).trim(); return INTERPRETATION_TEXT[text] || text; }
/** Heating months before cooling months, then by month, so January heating always leads. */
function pairOrder(a, b) { const pa = /^(HDD|CDD)-(\d{2})$/.exec(String(a)); const pb = /^(HDD|CDD)-(\d{2})$/.exec(String(b)); if (!pa || !pb) return String(a).localeCompare(String(b)); return (pa[1] === 'HDD' ? 0 : 1) - (pb[1] === 'HDD' ? 0 : 1) || Number(pa[2]) - Number(pb[2]); }
/** A table cell with a headline value and a smaller line under it. */
function stacked(main, sub, { wrap = false } = {}) { const cell = node('span', main); if (sub) cell.append(node('span', sub, { class: wrap ? 'band wrap' : 'band' })); return cell; }
function strategyText(value) { const text = String(value || ''); if (STRATEGY_TEXT[text]) return STRATEGY_TEXT[text]; const add = /^add_(USW\d{8})$/.exec(text); return add ? `Add ${stationCity(add[1])}` : humanize(text); }
function plainScope(text) { return text == null ? NA : String(text).replace(/\b(HDD|CDD)-(\d{2})\b/g, (id) => pairLabel(id)); }
function protocolText(value) { if (value == null || value === '') return NA; const text = String(value); return PROTOCOL_TEXT[text] || humanize(text); }
function countyName(fips, countyFor) { const county = countyFor ? countyFor(fips) : null; return county ? countyLabel(county, fips) : `County ${fips}`; }
function yearText(value) { return finite(value) ? String(Math.trunc(Number(value))) : NA; }
function pointsText(value) { return finite(value) ? `${num(Math.abs(Number(value)) * 100, 1)} points` : NA; }
function titleCase(text) { return String(text || '').toLowerCase().replace(/\b[a-z]/g, (c) => c.toUpperCase()); }
const yesNo = (value) => (value === true ? 'Yes' : value === false ? 'No' : NA);
function scoredText(value) { if (value == null) return NA; return STATUS_WORD[String(value)] || humanize(value); }

/* ---------- DOM helpers ---------- */
const para = (text, className) => node('p', text, className ? { class: className } : {});
const lead = (text) => node('p', text, { class: 'doc-lead' });
const heading = (text) => node('h4', text);
function externalLink(text, href) { return node('a', text, { href, rel: 'noopener', target: '_blank' }); }
function fragment(parts) { const span = document.createDocumentFragment(); parts.forEach((part) => span.append(typeof part === 'string' ? document.createTextNode(part) : part)); return span; }
function sentence(parts, className) { const p = node('p', undefined, className ? { class: className } : {}); p.append(fragment(parts)); return p; }
/** Standing of the record, in a reader's terms. The recorded status code itself stays in the
 *  provenance block: "partial" on fifteen records in a row reads as a machine light, not a caution. */
function statusCallout(record) {
  const complete = record.status === 'available' && !record.reason_code;
  const text = complete ? 'Everything the release recorded for this study is published on this page.' : (REASON_TEXT[record.reason_code] || statusText(record));
  const label = complete ? 'Complete record.' : record.status === 'unavailable' ? 'Not published in this release.' : 'How to read this.';
  const box = node('p', undefined, { class: `callout${complete ? ' callout-info' : ''}`, role: 'note' });
  box.append(node('strong', `${label} `), document.createTextNode(text));
  return box;
}
function fieldsDetails(payload, countyFor) {
  const details = node('details', undefined, { class: 'plain fields' });
  details.append(node('summary', 'All reported fields'), para('Everything the release recorded for this item, with field names spelled out. Digests and identifiers are listed separately under "Provenance and identifiers".', 'note'));
  details.append(payload && typeof payload === 'object' && Object.keys(payload).length ? structured('', payload, 0, countyFor) : para('No further fields are recorded.', 'note'));
  return details;
}
function article(key, children) {
  const wrap = node('article', undefined, { class: 'research-record', id: `research-${String(key).replace(/^research:/, '').replace(/[^a-z0-9_-]/gi, '-')}` });
  const title = node('h3', recordMeta(key).title, { tabindex: '-1' });
  wrap.append(title, ...children.filter(Boolean));
  return wrap;
}

/* ---------- identifier sweep: digests and ids leave the visible fields and join the provenance block ---------- */
const atomic = (value) => value === null || typeof value !== 'object';
function sweepIdentifiers(value, label, countyFor, out) {
  if (atomic(value)) {
    if (typeof value === 'string' && isIdentifier(value)) { out.push([label || 'Identifier', value]); return undefined; }
    return value;
  }
  if (Array.isArray(value)) {
    if (value.every(atomic)) {
      const ids = value.filter((item) => typeof item === 'string' && isIdentifier(item));
      if (ids.length) out.push([label || 'Identifiers', ids]);
      const rest = value.filter((item) => !(typeof item === 'string' && isIdentifier(item)));
      return rest.length || !value.length ? rest : undefined;
    }
    const items = value.map((item, index) => sweepIdentifiers(item, `${label || 'Item'} ${num(index + 1)}`, countyFor, out)).filter((item) => item !== undefined);
    return items.length || !value.length ? items : undefined;
  }
  const entries = Object.entries(value)
    .map(([name, item]) => [name, sweepIdentifiers(item, label ? `${label} · ${fieldLabel(name, countyFor)}` : fieldLabel(name, countyFor), countyFor, out)])
    .filter(([, item]) => item !== undefined);
  if (!entries.length && Object.keys(value).length) return undefined;
  return Object.fromEntries(entries);
}
/** Provenance for one record. The release identifier is published in full once, in
 *  "This release"; every other record carries its short form so the page is not
 *  repeating a 64-character string sixteen times. */
function recordProvenance(record, extra = []) {
  if (!record) return provenanceBlock(extra);
  const sources = record.source_artifact_ids || [];
  /** An empty list is not a value: it would print a labelled blank row. */
  const filled = (value) => (Array.isArray(value) ? (value.length ? value : undefined) : value);
  return provenanceBlock([
    ['Release', releaseLabel(record.release_id)],
    ['Result object', record.object_id], ['Analysis', record.analysis_id], ['Data vintage', record.data_vintage_id],
    ['Models', filled(record.model_spec_ids)], ['Scenario set', record.scenario_set_id], ['Valuation date', record.valuation_asof],
    ['Evidence', record.evidence_reference],
    ['Sources', filled(sources.slice(0, 6).concat(sources.length > 6 ? [`… ${sources.length - 6} more`] : []))],
    ['Recorded status', record.reason_code ? `${record.status} · ${record.reason_code}` : record.status],
    ...extra,
  ]);
}
/** The collapsed "All reported fields" block plus the provenance block, with swept identifiers appended once. */
function recordFooter(record, payload, countyFor, extras = []) {
  const swept = []; const clean = sweepIdentifiers(payload || {}, '', countyFor, swept) ?? {};
  const known = new Set(extras.map(([, value]) => String(value)));
  const ids = swept.filter(([, value]) => !known.has(String(value)));
  return [fieldsDetails(clean, countyFor), recordProvenance(record, [...extras, ...ids])];
}

/* ---------- generic structured tree (kept from V2, with humanised keys and formatted values) ---------- */
function fieldLabel(key, countyFor) {
  const text = String(key);
  if (LABELS[text]) return LABELS[text];
  const county = /^(\d{5}):((?:HDD|CDD)-\d{2})$/.exec(text); if (county) return `${countyName(county[1], countyFor)} · ${pairLabel(county[2], { short: true })}`;
  const station = /^(USW\d{8}):((?:HDD|CDD)-\d{2})$/.exec(text); if (station) return `${stationCity(station[1])} · ${pairLabel(station[2], { short: true })}`;
  if (/^USW\d{8}(\|USW\d{8})+$/.test(text)) return stationSet(text);
  if (isStation(text)) return stationLabel(text);
  if (/^add_USW\d{8}$/.test(text)) return strategyText(text);
  if (isPair(text)) return pairLabel(text);
  return humanize(text);
}
function atomNode(key, value) {
  const name = String(key || '');
  if (value === null || value === undefined || value === '') return document.createTextNode(NA);
  if (typeof value === 'boolean') return document.createTextNode(yesNo(value));
  if (typeof value === 'number') {
    if (/bytes/.test(name)) return document.createTextNode(bytesText(value));
    if (/seconds/.test(name)) return document.createTextNode(secondsText(value));
    if (/fraction|share/.test(name)) return document.createTextNode(pct(value));
    if (Number.isInteger(value)) return document.createTextNode(num(value));
    return document.createTextNode(num(value, Math.abs(value) < 1 ? 4 : 2));
  }
  const text = String(value);
  if (isIdentifier(text)) return node('code', text);
  if (/^https?:\/\//.test(text)) return externalLink(text.replace(/^https?:\/\//, ''), text);
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) return document.createTextNode(dateShort(text));
  if (/^\d{4}-\d{2}$/.test(text)) return document.createTextNode(monthText(text));
  if (isStation(text)) return document.createTextNode(stationLabel(text));
  if (isPair(text)) return document.createTextNode(pairLabel(text));
  if (/^add_USW\d{8}$/.test(text) || STRATEGY_TEXT[text]) return document.createTextNode(strategyText(text));
  if (/disposition/.test(name)) return document.createTextNode(dispositionText(text));
  if (/^(baseline|challenger|common_support|inference_unit)$/.test(name)) return document.createTextNode(protocolText(text));
  if (/^(scoreability|status|admission_status|reason|unavailable_reason|registry_role|objective|sensitivity)$/.test(name)) {
    if (name === 'admission_status') return document.createTextNode(ADMISSION_TEXT[text] || humanize(text));
    if (name === 'registry_role') return document.createTextNode(ROLE_TEXT[text] || humanize(text));
    if (name === 'objective') return document.createTextNode(OBJECTIVE_TEXT[text] || humanize(text));
    if (/^(reason|unavailable_reason)$/.test(name)) return document.createTextNode(REASON_TEXT[text] || statusText(text));
    if (name === 'status' && PROTOCOL_TEXT[text]) return document.createTextNode(PROTOCOL_TEXT[text]);
    return document.createTextNode(/\s/.test(text) ? text : humanize(text));
  }
  return document.createTextNode(text);
}
function structured(label, value, depth = 0, countyFor) {
  if (atomic(value)) return kvTable([[fieldLabel(label, countyFor), atomNode(label, value)]]);
  if (Array.isArray(value) && value.every(atomic)) {
    if (!value.length) return para('No items recorded.', 'note');
    return dataTable(['Item', 'Value'], value.map((item, index) => [num(index + 1), atomNode(label, item)]), { numeric: [0] });
  }
  const section = node('section', undefined, { class: 'research-data' });
  if (label) section.append(node(depth > 1 ? 'h5' : 'h4', fieldLabel(label, countyFor)));
  if (Array.isArray(value)) {
    const flat = value.length && value.every((item) => item && typeof item === 'object' && !Array.isArray(item) && Object.values(item).every(atomic));
    if (flat) {
      const columns = [...new Set(value.flatMap((item) => Object.keys(item)))];
      const numeric = columns.map((column, index) => (value.every((item) => item[column] == null || typeof item[column] === 'number') ? index : -1)).filter((index) => index >= 0);
      section.append(dataTable(columns.map((column) => fieldLabel(column, countyFor)), value.map((item) => columns.map((column) => atomNode(column, item[column]))), { numeric }));
      return section;
    }
    value.forEach((item, index) => { const detail = node('details'); detail.append(node('summary', `${fieldLabel(label || 'item', countyFor)} ${num(index + 1)}`), structured('', item, depth + 1, countyFor)); section.append(detail); });
    return section;
  }
  const entries = Object.entries(value); const fields = entries.filter(([, item]) => atomic(item));
  if (fields.length) section.append(kvTable(fields.map(([name, item]) => [fieldLabel(name, countyFor), atomNode(name, item)])));
  entries.filter(([, item]) => !atomic(item)).forEach(([name, item]) => { const detail = node('details'); detail.append(node('summary', fieldLabel(name, countyFor)), structured('', item, depth + 1, countyFor)); section.append(detail); });
  return section;
}

/* ---------- Start here ---------- */
function renderAbout({ pageLink, select, bootstrap }) {
  const counties = bootstrap?.county_registry?.length;
  const indexes = (bootstrap?.index_definitions || []).filter((item) => isPair(item?.id));
  const heating = indexes.filter((item) => item.id.startsWith('HDD')).length;
  const listed = Object.values(STATIONS).filter((station) => station.role === 'listed').length;
  const scale = counties || indexes.length ? tiles([
    tile('Counties studied', counties ? num(counties) : NA, 'every county in the contiguous United States'),
    tile('Monthly indexes', indexes.length ? num(indexes.length) : NA, heating ? `${num(heating)} heating months and ${num(indexes.length - heating)} cooling months of the year` : 'one heating or cooling index per month'),
    tile('Stations you could hedge with', listed ? num(listed) : NA, 'the U.S. cities with exchange-listed temperature contracts'),
  ]) : null;
  const links = node('div', undefined, { class: 'link-row record-actions' });
  links.append(linkButton('Explore the map', pageLink('index.html')), linkButton('Contract Lab', pageLink('contract.html'), { quiet: true }), linkButton('Portfolio Lab', pageLink('portfolio.html'), { quiet: true }));
  const next = node('p', undefined, { class: 'note' });
  const glossary = node('button', 'glossary', { type: 'button', class: 'linklike' }); glossary.addEventListener('click', () => select('research:glossary', true));
  const limits = node('button', 'limits of this release', { type: 'button', class: 'linklike' }); limits.addEventListener('click', () => select('research:limitations', true));
  const r01 = node('button', 'R01', { type: 'button', class: 'linklike' }); r01.addEventListener('click', () => select('research:r01', true));
  next.append(fragment(['Continue with the ', glossary, ', the ', limits, ', or the headline experiment, ', r01, '.']));
  return article(ABOUT_KEY, [
    lead('The Weather Basis Atlas asks one question for every county in the contiguous United States: if you had to protect yourself against a cold January or a hot July using only the thirteen weather stations that actually have listed temperature contracts, how much of your own county\'s weather would that protection have covered?'),
    scale,
    heading('Degree days'),
    para('A heating degree day measures how far a day\'s mean temperature falls below 65 °F; a cooling degree day measures how far it rises above 65 °F. Every degree below the base counts as one heating degree day for that day, and every degree above it as one cooling degree day. The atlas computes them from daily temperatures and sums them over a calendar month, so "January heating degree days" is one number per county per year: a cold January is a large number, a mild one is small.'),
    heading('Basis risk'),
    para('A weather contract settles on a named station, not on your county. If the station has a mild January while your county is cold, the contract pays little while your heating bill is high. The gap between the index you can trade and the weather you actually have is basis risk. It cannot be removed by buying more of the same contract; it can only be measured and, sometimes, reduced by choosing a better station.'),
    heading('Why only thirteen stations matter'),
    para('Exchange-listed U.S. temperature contracts exist for thirteen cities. Every county in the atlas is matched against those thirteen stations and no others, because those are the only indexes a hedger could actually have used. Five Nebraska airports also appear in the case studies as unlisted research proxies; they are never presented as tradable.'),
    heading('Reading the numbers'),
    para('Hedge effectiveness is the share of a county\'s year-to-year variation in the monthly index that a listed station\'s index would have explained, on the historical seasons where both records exist. 100% means the station tracks the county perfectly; 0% means it explains nothing. Gain versus nearest is the difference, in percentage points, between the station the atlas selects using only information available at the decision date and the station that is simply closest. A positive gain means the selection rule helped; a negative one means the nearest station would have done better.'),
    heading('How the atlas picks a station'),
    para('For each county and month the atlas applies one rule, called the prior-best rule: at the decision date, choose the listed station whose past performance for that county scored best. The Explore page labels each selected station "chosen by the prior-best rule". Experiment R01 in this library tests that rule against simply taking the nearest station, and reports that the nearest station did better in most county-months. The rule is kept because it is the one the release registered; the evidence for and against it is published here rather than hidden.'),
    heading('The 2,000 simulated seasons'),
    para('The Contract Lab and Portfolio Lab value payoffs against 2,000 simulated weather paths covering the twelve months after the valuation date. Each path is a full year of daily temperatures for every county and station at once, drawn from a weather generator fitted to the fixed public temperature record, so a contract and the county it hedges are always evaluated on the same simulated weather. Expected values and expected shortfalls on those pages are averages over these paths and nothing more.'),
    heading('What the site does not do'),
    para('This release publishes no market prices: no bids, offers, premiums or exchange settlement values are reproduced or estimated anywhere in it. The preserved first edition, linked from the footer, does show modelled bid and ask indications; they were withdrawn from the current release and are not quotes either. There are no weather forecasts: the simulated seasons describe the historical range of outcomes, not what next winter will bring. Nothing here is investment advice, insurance or a promise of hedge performance. The atlas is a research and education project built from public NOAA temperature records, and every number can be traced to one fixed data vintage through the provenance block at the end of each record.'),
    links, next,
  ]);
}

function renderGlossary(key, record, { countyFor }) {
  const payload = record.payload || {};
  const plain = [
    ['Heating degree days (HDD)', 'How much colder than 65 °F each day was, summed over a month. A larger number means a colder month.'],
    ['Cooling degree days (CDD)', 'How much warmer than 65 °F each day was, summed over a month. A larger number means a hotter month.'],
    ['Basis risk', 'The mismatch between the station index a contract settles on and the county weather you actually experience.'],
    ['Hedge effectiveness', 'The share of a county\'s year-to-year index variation that a station\'s index would have explained on matched historical seasons. Higher is better.'],
    ['Gain versus nearest', 'Hedge effectiveness of the selected station minus that of the closest listed station, in percentage points. Negative means the nearest station would have hedged better.'],
    ['Prior-best rule', 'The atlas\'s station-selection rule: at the decision date, pick the listed station whose past performance for this county scored best. Explore labels selected stations as chosen by this rule.'],
    ['Strike', 'The index level at which a contract starts to pay. A call pays when the month\'s index finishes above the strike; a put pays when it finishes below.'],
    ['Multiplier', 'Dollars paid per degree day beyond the strike. It converts a weather index into money.'],
    ['Expected shortfall', 'The average loss in the worst slice of outcomes, for example the worst 10% (written ES90). It describes how bad the bad cases are, not the typical case.'],
    ['Decision point', 'A date at which a station choice is made using only information available before it. Each historical decision point is one unit of evidence; the records call these origins.'],
    ['Matched seasons', 'Historical years for which both the county record and the station record exist, so the two can be compared fairly.'],
    ['95% band', 'A range around an estimate. Where it includes zero, the evidence does not separate the result from no effect.'],
  ];
  const registered = (payload.terms || []).map((item) => ({ name: GLOSSARY_TERMS[item.term] || humanize(item.term), plain: GLOSSARY_PLAIN[item.term] || item.definition, exact: item.definition }));
  const wording = registered.length ? node('details', undefined, { class: 'plain' }) : null;
  if (wording) wording.append(node('summary', 'Registered wording, as recorded'), dataTable(['Term', 'Registered definition'], registered.map((item) => [item.name, item.exact || NA])));
  return article(key, [
    lead('Terms used across the atlas, in plain words. The second table explains the definitions the release registered; the exact registered wording is kept underneath for anyone reproducing a result.'),
    statusCallout(record),
    para('Every index in this release is defined the same way: heating and cooling degree days with a 65 °F base, computed day by day from temperature and then summed over the month.'),
    heading('Everyday terms'),
    dataTable(['Term', 'Meaning'], plain),
    heading('Terms the release registered'),
    registered.length ? dataTable(['Term', 'What it means'], registered.map((item) => [item.name, item.plain])) : para('No registered terms are published.', 'note'),
    wording,
    ...recordFooter(record, payload, countyFor),
  ]);
}

function renderLimitations(key, record, { countyFor }) {
  const payload = record.payload || {}; const list = node('ul');
  (payload.items || []).forEach((item) => list.append(node('li', LIMIT_TEXT[String(item).trim()] || String(item))));
  return article(key, [
    lead('What this release can and cannot be used for. Each point below is recorded with the release and applies to every page on the site.'),
    statusCallout(record),
    list.childElementCount ? list : para('No limits are recorded.', 'note'),
    para('These are written out here in everyday words; the exact recorded wording is under "All reported fields". Negative and inconclusive findings are published alongside positive ones, and each registered experiment gives the detail behind the limit it created.', 'note'),
    ...recordFooter(record, payload, countyFor),
  ]);
}

/** Recorded source wording carries field and variable names; these are the same statements in words. */
const AGGREGATION_TEXT = {
  'Daily county mean temperature then degree-day transform then period sum.': 'Daily county mean temperature, turned into degree days one day at a time, then added up over the month.',
  'Daily county Tmax retains source order; no multivariable product past coherent_through.': 'Daily county maximum, kept in the order it was published. Nothing that combines it with the other series is supported past the last month they agree.',
  'Daily county Tmin retains source order; no multivariable product past coherent_through.': 'Daily county minimum, kept in the order it was published. Nothing that combines it with the other series is supported past the last month they agree.',
  'Daily station Tmax/Tmin arithmetic mean then degree-day transform then period sum.': 'The average of the station\'s daily maximum and minimum, turned into degree days one day at a time, then added up over the month.',
};
const UNSUPPORTED_TEXT = {
  'County mean temperature is not official station settlement or a business loss model.': 'It is a county average, not the settlement value of a station contract, and it is not a model of anyone\'s losses.',
  'TAVG/TMAX/TMIN coherence after 2025-12 is unsupported; observed mismatch reached about 6.92 F in 2026.': 'After Dec 2025 the mean, maximum and minimum county series stop agreeing with each other — the gap reached about 6.92 °F in 2026 — so nothing that combines them holds past that month.',
  'GHCN proxy observations are not official settlement records.': 'These are public station observations standing in for an index, not official settlement records.',
};
const AVAILABILITY_TEXT = {
  'retrospective revised public snapshot; historical issue-time availability is unknown.': 'The county records are a present-day, revised snapshot. What they looked like when a past season was under way is not known.',
  'retrospective public snapshot; historical availability and official settlement corrections are unknown.': 'The station records are a present-day snapshot. Neither their availability at the time nor any later official correction is known.',
};
function plainSourceText(text, map) {
  const raw = String(text || ''); if (!raw) return '';
  if (map && map[raw]) return map[raw];
  return raw.replace(/\b(\d{4})-(\d{2})\b/g, (whole, year, month) => `${MONTHS_SHORT[Number(month) - 1]} ${year}`).replace(/(\d)\s*F\b/g, '$1 °F');
}
function monthRange(start, end) { if (!start && !end) return NA; return `${monthText(start)} to ${monthText(end)}`; }
function vintageDate(id) { const match = /(\d{4}-\d{2}-\d{2})/.exec(String(id || '')); return match ? dateShort(match[1]) : null; }
function renderSources(key, record, { countyFor, bootstrap, select }) {
  const payload = record.payload || {}; const sources = payload.sources || [];
  const vintage = key === 'research:data';
  const rows = sources.map((item) => [
    stacked(SOURCE_NAMES[item.support_id] || humanize(item.support_id), `${VARIABLE_TEXT[item.variable] || item.variable || NA}, by ${item.location_type || 'location'}`, { wrap: true }),
    monthRange(item.coverage_start, item.coverage_end), monthText(item.coherent_through),
    plainSourceText(item.aggregation_order, AGGREGATION_TEXT) || NA, plainSourceText(item.unsupported_reason, UNSUPPORTED_TEXT) || NA,
  ]);
  const availability = [...new Set(sources.map((item) => item.historical_availability).filter(Boolean))];
  const availabilityList = node('ul');
  availability.forEach((item) => availabilityList.append(node('li', plainSourceText(item, AVAILABILITY_TEXT).replace(/^./, (c) => c.toUpperCase()))));
  const fixedOn = vintageDate(payload.vintage_id);
  const ends = [...new Set(sources.map((item) => item.coverage_end).filter(Boolean))].sort().at(-1);
  const coherent = [...new Set(sources.map((item) => item.coherent_through).filter(Boolean))].sort()[0];
  const sourcesLink = node('button', 'Where the temperature data come from', { type: 'button', class: 'linklike' });
  if (select) sourcesLink.addEventListener('click', () => select('research:source_support', true));
  const sourceTable = rows.length ? dataTable(['Source and what it measures', 'Covers', 'Series agree through', 'How it is added up', 'What it cannot be used for'], rows) : para('No sources are recorded.', 'note');
  const vintageSources = vintage ? node('details', undefined, { class: 'plain' }) : null;
  if (vintageSources) vintageSources.append(node('summary', `The ${num(sources.length)} records inside the fixed copy`), sourceTable, para('The same table, with everything each record can and cannot be used for, is the subject of the data sources record.', 'note'));
  return article(key, [
    lead(vintage
      ? 'Every page on this site computes from one fixed copy of the public temperature record, taken on a single day and never updated afterwards. This record says when that copy was taken, how far it reaches, and what it cannot stand in for.'
      : 'Every number on this site is computed from a small set of public temperature records. This table says what each one is, what period it covers, and what it cannot be used for.'),
    statusCallout(record),
    vintage && fixedOn ? tiles([
      tile('Data fixed on', fixedOn, 'nothing published here changes after this date', { small: true }),
      tile('Temperature record reaches', monthText(ends), 'last month of daily observations included', { small: true }),
      tile('Series agree through', monthText(coherent), 'after this month the county series stop agreeing with each other', { small: true }),
      tile('Valued as of', dateShort(record.valuation_asof || bootstrap?.defaults?.valuation_asof), 'the date all contract values are quoted from', { small: true }),
    ]) : null,
    payload.market_status ? para(MARKET_TEXT[payload.market_status] || humanize(payload.market_status)) : null,
    payload.settlement_status ? para(MARKET_TEXT[payload.settlement_status] || humanize(payload.settlement_status)) : null,
    vintage ? null : heading('Sources'),
    vintage ? null : sourceTable,
    vintage ? null : para('"Series agree through" is the last month for which the county mean, maximum and minimum temperatures are consistent with one another. After that month, anything that combines them is not supported.', 'note'),
    !vintage && availability.length ? heading('How available these records were at the time') : null,
    !vintage && availability.length ? availabilityList : null,
    !vintage && availability.length ? para('Every figure on the site is computed from today\'s revised data, so nothing here reproduces what a hedger could actually have seen at the time.', 'note') : null,
    vintage ? para('Nothing on this site is recomputed when NOAA publishes a revision. That is deliberate: it means a link you share today shows the same numbers next year. It also means the figures drift further from the current published record as time passes.') : null,
    vintage ? vintageSources : null,
    vintage && select ? sentence([sourcesLink, ' sets out what each of those records measures, how far it reaches and what it cannot be used for.'], 'note') : null,
    ...recordFooter(record, { sources: payload.sources, market_status: payload.market_status, settlement_status: payload.settlement_status }, countyFor, [['Data vintage', payload.vintage_id], ['Data vintage digest', payload.vintage_sha256]]),
  ]);
}

/* ---------- Registered experiments ---------- */
/* Each block of the design record belongs to a full record elsewhere in the library. */
const METHOD_RECORD = { nebraska_case: 'research:nebraska', r01: 'research:r01', r02: 'research:r02', r03: 'research:r03', r04: 'research:r04', r05: 'research:r05' };
const METHOD_LINE = {
  nebraska_case: 'Five Nebraska counties, each with a nearby airport, used as the test bed for the basket, joint-book and next-station studies.',
  r01: 'Does picking the station with the best past performance beat simply picking the nearest one?',
  r02: 'Does a small basket of Nebraska stations hedge better than the single nearest station?',
  r03: 'Is one joint five-county book better than five separate county hedges?',
  r04: 'Which of three candidate weather generators reproduces observed seasons most closely?',
  r05: 'Where does basis risk stay high whatever screening setting is used?',
};
const METHOD_FIELD = { policy: 'What was compared', selection: 'How stations were chosen', scope: 'What it covers', comparison: 'What was compared', unit_of_inference: 'Unit of evidence', status: 'Registration', question: 'Registered question', disposition: 'Reading', origins: 'Decision points', selected_generator: 'Generator kept', interpretation: 'Reading' };
function renderMethod(key, record, { countyFor, select }) {
  const swept = []; const payload = record.payload || {};
  const parts = [
    lead('One screen showing how each registered experiment and the Nebraska case were set up: what was compared, on what evidence, and what counts as an answer. Every block links to the record that reports the result.'),
    statusCallout(record),
    para('The wording here is written out in everyday terms. The exact registered wording for each field is kept under "All reported fields" at the foot of this record.', 'note'),
  ];
  Object.entries(payload).forEach(([name, item]) => {
    const target = METHOD_RECORD[name];
    parts.push(heading(target ? recordMeta(target).title : fieldLabel(name, countyFor)));
    if (METHOD_LINE[name]) parts.push(para(METHOD_LINE[name]));
    if (!item || typeof item !== 'object') { parts.push(para(String(item ?? NA))); return; }
    const rows = [];
    Object.entries(item).forEach(([field, value]) => {
      if (field === 'locations' || field === 'mapping') return;
      if (typeof value === 'string' && isIdentifier(value)) { swept.push([`${recordMeta(target || name).toc} · ${METHOD_FIELD[field] || fieldLabel(field, countyFor)}`, value]); return; }
      const label = METHOD_FIELD[field] || fieldLabel(field, countyFor);
      if (field === 'disposition') { rows.push([label, dispositionText(value)]); return; }
      if (field === 'selected_generator') { rows.push([label, GENERATOR_TEXT[String(value)] || humanize(value)]); swept.push([`${recordMeta(target || name).toc} · generator`, value]); return; }
      if (field === 'question') { rows.push([label, `“${value}”`]); return; }
      if (field === 'interpretation') { rows.push([label, interpretationText(value)]); return; }
      if (Array.isArray(value)) { rows.push([label, value.map((entry) => (isPair(entry) ? pairLabel(entry) : String(entry))).join(', ')]); return; }
      if (atomic(value)) { rows.push([label, PROTOCOL_TEXT[String(value)] || plainScope(value)]); return; }
      swept.push([`${recordMeta(target || name).toc} · ${label}`, JSON.stringify(value)]);
    });
    if (rows.length) parts.push(kvTable(rows));
    const locations = item.locations || item.mapping;
    if (Array.isArray(locations) && locations.length) {
      parts.push(dataTable(['County', 'Place', 'Nearby airport (not listed)'], locations.map((row) => [countyLabel(countyFor?.(row.fips), row.fips) || row.county, row.place, stationLabel(row.station)])));
    }
    if (target && select) {
      const link = node('button', recordMeta(target).toc, { type: 'button', class: 'linklike', 'aria-label': `Read the full record: ${recordMeta(target).title}` });
      link.addEventListener('click', () => select(target, true));
      parts.push(sentence(['Results: ', link, '.'], 'note'));
    }
  });
  parts.push(...recordFooter(record, payload, countyFor, swept));
  return article(key, parts);
}

/* National tally of the prior-best rule against the nearest station, from the 14 public county summaries.
   Computed once per page life; the same summaries drive the Explore map's "Gain vs nearest station" layer. */
let tallyPromise = null;
function nationalTally(bootstrap, loadObject) {
  if (tallyPromise) return tallyPromise;
  const defined = (bootstrap.index_definitions || []).map((item) => item?.id).filter(isPair);
  const fromKeys = bootstrap.objects.map((item) => item.object_key || item.object_id).filter((id) => typeof id === 'string' && id.startsWith('summary:')).map((id) => id.slice('summary:'.length)).filter(isPair);
  const pairs = defined.length ? defined : fromKeys;
  tallyPromise = Promise.all(pairs.map(async (pair) => {
    try {
      const summary = await loadObject(`summary:${pair}`);
      const rows = Array.isArray(summary?.payload?.rows) ? summary.payload.rows : [];
      const counts = { pair, ok: true, records: rows.length, wins: 0, ties: 0, losses: 0, unavailable: 0 };
      rows.forEach((row) => {
        const value = row?.layers?.delta_he?.value;
        if (value === null || value === undefined || !Number.isFinite(Number(value))) counts.unavailable += 1;
        else if (Number(value) > 0) counts.wins += 1;
        else if (Number(value) < 0) counts.losses += 1;
        else counts.ties += 1;
      });
      return counts;
    } catch (error) { return { pair, ok: false, message: error.message }; }
  }));
  return tallyPromise;
}
function renderTally(tally, bands, pageLink) {
  const loaded = tally.filter((item) => item.ok); const failed = tally.filter((item) => !item.ok);
  if (!loaded.length) return [para('The public county summaries could not be loaded, so the wins, ties and losses cannot be counted here. The release\'s own figures are still shown below.', 'callout callout-warn')];
  const sum = (field) => loaded.reduce((acc, item) => acc + item[field], 0);
  const wins = sum('wins'); const ties = sum('ties'); const losses = sum('losses'); const unavailable = sum('unavailable'); const records = sum('records'); const evaluable = wins + ties + losses;
  const bandText = bands.length ? listText(bands.map((band) => `${num(Number(band) * 100)}`)) : null;
  const answer = sentence([
    `Across all ${num(records)} county-and-month records in the atlas, the prior-best rule beat the nearest listed station in `, node('strong', `${num(wins)} of them`), ` (${pct(wins / evaluable)} of the ${num(evaluable)} that could be scored), matched it exactly in ${num(ties)} (${pct(ties / evaluable)}), and did worse in ${num(losses)}: `,
    node('strong', `the nearest station hedged better in ${pct(losses / evaluable, 0)} of the records that could be scored`), `. The remaining ${num(unavailable)} had no seasons in common to score.`,
  ]);
  const totals = [node('strong', 'All indexes'), num(wins), num(ties), num(losses), num(unavailable), pct(losses / evaluable, 0)];
  totals.__class = 'is-selected';
  const rows = loaded.map((item) => { const ev = item.wins + item.ties + item.losses; return [pairLabel(item.pair), num(item.wins), num(item.ties), num(item.losses), num(item.unavailable), pct(ev ? item.losses / ev : null, 0)]; })
    .concat(failed.map((item) => { const row = [pairLabel(item.pair), NA, NA, NA, NA, NA]; row.__class = 'is-muted'; return row; }))
    .concat([totals]);
  const explore = node('a', 'the Explore map', { href: pageLink('index.html') });
  return [
    answer,
    tiles([
      tile('Prior-best rule hedged better', num(wins), `${pct(wins / evaluable)} of scored records`),
      tile('Exactly equal', num(ties), `${pct(ties / evaluable)} · the two rules picked equally well`),
      tile('Nearest station hedged better', num(losses), `${pct(losses / evaluable)} of scored records`),
      tile('Could not be scored', num(unavailable), 'no seasons the two records share'),
    ]),
    heading('Index by index'),
    dataTable(['Index', 'Prior-best better', 'Equal', 'Nearest better', 'Not scored', 'Nearest better (share)'], rows, { numeric: [1, 2, 3, 4, 5] }),
    para('One row per index. "Prior-best better" counts the counties where the station chosen by past performance removed more of the county\'s year-to-year variation than the nearest listed station would have, on the seasons both records share.', 'note'),
    sentence(['These counts are worked out in your browser from the same public county summaries that draw the "Gain vs nearest station" layer on ', explore, ', so the two views cannot disagree. The release\'s own record publishes the win count only; the ties, the losses and the shares above are counted here.'], 'note'),
    bandText ? para(`The study also registered practical-equivalence margins of ${bandText} percentage points — differences smaller than these were meant to count as no real difference — but this release never counted the results against them. The "equal" column above therefore holds exact ties only, and a reading that used those margins would move some narrow wins and losses into it.`) : null,
    sentence(['The atlas still selects stations with the prior-best rule despite this result. On ', node('a', 'the Explore map', { href: pageLink('index.html') }), ' every selected station is labelled "chosen by the prior-best rule", and the "Gain vs nearest station" tile shows whether the rule helped or hurt in the county you are looking at.']),
  ];
}
function renderR01(key, record, { countyFor, bootstrap, loadObject, pageLink }) {
  const payload = record.payload || {}; const results = payload.results || {}; const protocol = payload.protocol || {};
  const total = results.county_window_records; const evaluable = results.evaluable; const won = results.prior_best_exceeds_nearest; const share = results.fraction_of_evaluable; const unavailable = results.unavailable;
  const bands = Array.isArray(protocol.equivalence_bands) ? protocol.equivalence_bands.filter(finite) : [];
  const own = finite(evaluable) && finite(won)
    ? `The release's own record publishes one number: ${num(won)} wins for the prior-best rule out of ${num(evaluable)} records that could be scored (${pct(share)}), with ${num(unavailable)} of ${num(total)} records left unscored. In the release's words: “${payload.interpretation || ''}”`.trim()
    : payload.interpretation || 'No result values are recorded.';
  const holder = node('div', undefined, { class: 'stack tally' });
  holder.append(para('Counting wins, ties and losses from the public county summaries…', 'status'));
  nationalTally(bootstrap, loadObject).then((tally) => holder.replaceChildren(...renderTally(tally, bands, pageLink).filter(Boolean)));
  return article(key, [
    lead('Every county and month was tested two ways on exactly the same seasons: hedge with the nearest listed station, or hedge with the station whose past performance scored best at the decision date. This record shows the whole picture — wins, ties and losses — not just the wins.'),
    statusCallout(record),
    heading('What the whole comparison shows'),
    holder,
    heading('How it was tested'),
    kvTable([
      ['The rule being challenged', protocolText(protocol.baseline)],
      ['The rule being tested', protocolText(protocol.challenger)],
      ['Compared on', protocolText(protocol.common_support)],
      ['What counts as one piece of evidence', protocolText(protocol.inference_unit)],
      ['What is measured', protocolText(protocol.metric)],
      ['Practical-equivalence margins', bands.length ? `${listText(bands.map((band) => `${num(Number(band) * 100)}`))} percentage points, registered in advance but never counted in this release` : NA],
      ['What it covers', protocolText(payload.scope)],
      ['Registration', protocolText(protocol.status)],
    ]),
    protocol.question ? para(`The question as registered, word for word: “${protocol.question}”`, 'note') : null,
    heading('What the release record itself reports'),
    para(own),
    ...recordFooter(record, payload, countyFor, [['Registration record', protocol.id], ['Metric definition', protocol.metric], ['Matched table digest', payload.matched_table_sha256]]),
  ]);
}

function renderR02(key, record, { countyFor }) {
  const payload = record.payload || {}; const experiment = payload.registered_experiment || {}; const results = Array.isArray(experiment.results) ? experiment.results : [];
  const origins = [...new Set(results.map((row) => row.origins).filter(finite))];
  const improved = results.filter((row) => Array.isArray(row.paired_mean_ci95) && row.paired_mean_ci95[1] < 0);
  const answer = results.length
    ? `${improved.length ? `In ${num(improved.length)} of the ${num(results.length)} place-and-month comparisons the basket hedged better and the whole 95% band stayed below zero: ${listText(improved.map((row) => `${row.place} (${pairLabel(row.pair)})`))}. ` : `In none of the ${num(results.length)} comparisons did the basket's whole 95% band stay below zero. `}The other ${num(results.length - improved.length)} were inconclusive: the band crossed zero, so the evidence does not separate the basket from the single nearest station, and the simpler choice is kept there.`
    : 'No per-place results are recorded.';
  const pairs = [...new Set(results.map((row) => row.pair))].sort(pairOrder);
  const tables = pairs.flatMap((pair) => {
    const subset = results.filter((row) => row.pair === pair).sort((a, b) => String(a.place).localeCompare(String(b.place)));
    const rows = subset.map((row) => {
      const usual = Object.entries(row.top_basket_frequency || {}).sort((a, b) => b[1] - a[1])[0];
      const line = [
        row.place || NA, count(row.basket?.es), count(row.nearest?.es),
        stacked(signedCount(row.mean_paired_squared_loss_change), intervalText(row.paired_mean_ci95, (v) => signedCount(v))),
        usual ? stacked(stationSet(usual[0]), `chosen at ${num(usual[1])} of ${num(row.origins)} decision points`, { wrap: true }) : NA,
        dispositionShort(row.disposition),
      ];
      if (Array.isArray(row.paired_mean_ci95) && row.paired_mean_ci95[1] < 0) line.__class = 'is-selected';
      return line;
    });
    return [node('h5', pairLabel(pair)), dataTable(['Place', 'Worst-case loss, basket', 'Worst-case loss, nearest', 'Change in squared error', 'Basket usually chosen', 'Reading'], rows, { numeric: [1, 2, 3] })];
  });
  return article(key, [
    lead(`Five Nebraska places, two months each. For every one, a small basket of nearby research stations — chosen using only earlier seasons — is compared with the single nearest station across ${origins.length === 1 ? num(origins[0]) : 'the recorded'} decision points in date order.`),
    statusCallout(record),
    heading('What the baskets did'),
    para(answer),
    heading('Place by place'),
    ...tables,
    para(`The two loss columns are expected shortfall in degree days: the average of the worst hedged seasons, so lower is better. The change in squared error is basket minus nearest — a squared quantity, so read its sign and its size against the other rows rather than as degree days — and the smaller line under it is the 95% range across decision points. ${improved.length ? `The ${num(improved.length)} highlighted rows are the ones whose whole range stayed below zero, meaning the basket hedged better at every plausible reading of the evidence.` : 'No row had its whole range below zero.'}`, 'note'),
    para(`What this covers: ${plainScope(PROTOCOL_TEXT[String(experiment.scope || payload.limitations || '')] || experiment.scope || payload.limitations || '')}. It is a five-county study and says nothing about counties elsewhere.`, 'note'),
    ...recordFooter(record, payload, countyFor, [['Registration record', experiment.protocol_id]]),
  ]);
}

function renderR03(key, record, { countyFor }) {
  const payload = record.payload || {}; const experiment = payload.registered_experiment || {};
  const results = (Array.isArray(experiment.results) ? [...experiment.results] : []).sort((a, b) => pairOrder(a.pair, b.pair));
  const sentences = results.map((row) => {
    const ci = row.paired_mean_ci95 || []; const crosses = ci.length === 2 && ci[0] < 0 && ci[1] > 0;
    return `For ${pairLabel(row.pair)}, the joint book left an average worst-case loss of ${count(row.joint?.es)} degree days against ${count(row.separate?.es)} for five separate hedges. Averaged over the ${num(row.origins)} decision points the change in squared error was ${signedCount(row.mean_paired_squared_loss_change)}, with a 95% band of ${intervalText(ci, (v) => signedCount(v))} — a band that ${crosses ? 'straddles zero, so the two approaches are not separated by this evidence' : 'stays clear of zero'}. Reading: ${dispositionText(row.disposition).toLowerCase()}.`;
  });
  /* One column per index, one row per measure: the eight-column version pushed half its
     columns off the side of the page, and there are only ever two indexes to compare. */
  const rows = results.length ? [
    ['Worst-case loss, one joint book', ...results.map((row) => count(row.joint?.es))],
    ['Worst-case loss, five separate hedges', ...results.map((row) => count(row.separate?.es))],
    ['Typical squared error, one joint book', ...results.map((row) => count(row.joint?.mse))],
    ['Typical squared error, five separate hedges', ...results.map((row) => count(row.separate?.mse))],
    ['Change in squared error, joint minus separate', ...results.map((row) => signedCount(row.mean_paired_squared_loss_change))],
    ['95% range for that change', ...results.map((row) => intervalText(row.paired_mean_ci95, (v) => signedCount(v)))],
    ['Decision points scored', ...results.map((row) => num(row.origins))],
  ] : [];
  return article(key, [
    lead('One five-county Nebraska book, hedged two ways against observed history: as a single joint book, or as five separate county hedges, with the same limit of five stations either way.'),
    statusCallout(record),
    heading('What the two ways of hedging did'),
    para(sentences.length ? sentences.join(' ') : 'No results are recorded.'),
    heading('Joint book against separate hedges'),
    rows.length ? dataTable(['Measure', ...results.map((row) => pairLabel(row.pair))], rows, { numeric: results.map((_, index) => index + 1) }) : null,
    para('Worst-case loss is expected shortfall in degree days: the average of the worst hedged seasons. Typical squared error is the release\'s mean squared error of what the hedge left behind — a squared quantity, so compare the two rows with each other rather than reading it as degree days. Both are lower-is-better, and the change is joint minus separate, so a negative number favours the joint book.', 'note'),
    para(`What this covers: ${PROTOCOL_TEXT[String(payload.limitations || '')] || plainScope(payload.limitations || '')}`, 'note'),
    ...recordFooter(record, payload, countyFor, [['Registration record', experiment.protocol_id]]),
  ]);
}

function renderR04(key, record, { countyFor }) {
  const payload = record.payload || {}; const report = payload.report || {}; const summary = report.summary || {}; const means = summary.mean_scores || {}; const rows = Array.isArray(report.rows) ? report.rows : [];
  const generators = Object.keys(means);
  const generatorLabel = (name) => GENERATOR_TEXT[name] || fieldLabel(name);
  const best = generators.filter((name) => finite(means[name]?.mean_crps)).sort((a, b) => Number(means[a].mean_crps) - Number(means[b].mean_crps))[0];
  const phrase = (name) => GENERATOR_PHRASE[name] || generatorLabel(name).toLowerCase();
  const scored = generators.map((name) => `${count(means[name]?.mean_crps, 1)} for the ${phrase(name)}`);
  const answer = `Only ${num(summary.n_scoreable_origins)} of the ${num(summary.n_registered_origins)} registered decision points could be scored. Averaged over those, the typical distance between the simulated spread of outcomes and what actually happened, in degree days, was ${listText(scored)} — lower is closer.${best ? ` The ${phrase(best)} came closest on this measure, but ${num(summary.n_scoreable_origins)} decision points are far too few to settle the question.` : ''}`;
  const scoreTable = (field) => dataTable(
    ['Decision point', 'Scored', ...generators.map((name) => GENERATOR_SHORT[name] || generatorLabel(name))],
    rows.map((row) => {
      const scores = row.scores || {};
      const line = [stacked(yearText(row.origin), `fitted to data up to ${dateShort(row.fit_cutoff)}`, { wrap: true }), scoredText(row.scoreability || row.status), ...generators.map((name) => count(scores[name]?.[field], 1))];
      if (row.reason) line.__class = 'is-muted';
      return line;
    }), { numeric: generators.map((_, index) => 2 + index) },
  );
  const notes = rows.filter((row) => row.reason).map((row) => `${yearText(row.origin)}: ${REASON_TEXT[row.reason] || statusText(row.reason)}`);
  return article(key, [
    lead('Three candidate weather generators produce the simulated seasons the Contract Lab and Portfolio Lab price against. Each was scored on how closely the spread of seasons it simulated matched what actually happened, at decision points registered in advance.'),
    statusCallout(record),
    heading('What the scoring showed'),
    para(answer),
    para(`Outcome: ${dispositionText(report.disposition).toLowerCase()}.`),
    report.prior_artifact_status ? para('An earlier run of this comparison is kept only as a record of a mistake: the counties it was configured with were not the counties it actually ran on. It plays no part in the choice of generator.', 'note') : null,
    heading('How far each generator was from what happened, in degree days'),
    rows.length ? scoreTable('mean_crps') : para('No decision points are recorded.', 'note'),
    para('Scored one index at a time and averaged. Lower is closer to what happened. The release calls this the mean CRPS.', 'note'),
    rows.length ? heading('The same test scoring all indexes together, in degree days') : null,
    rows.length ? scoreTable('energy_score') : null,
    rows.length ? para('This version scores a whole simulated year across every county and index at once, so it also rewards getting the relationships between them right. Again, lower is closer. The release calls this the energy score.', 'note') : null,
    notes.length ? para(notes.join(' '), 'note') : null,
    ...recordFooter(record, payload, countyFor, [['Registration record', report.protocol_id], ['Experiment', report.experiment_id], ['Producer', report.producer]]),
  ]);
}

function renderR05(key, record, { countyFor }) {
  const payload = record.payload || {}; const experiment = payload.registered_experiment || {}; const counts = experiment.classification_counts || {};
  const total = Object.values(counts).filter(finite).reduce((sum, value) => sum + Number(value), 0);
  const positive = counts.positive_in_screen; const ambiguous = counts.ambiguous; const difficult = counts.robustly_difficult;
  const answer = total
    ? `The screen was run ${num(experiment.settings)} times, each with a different setting, over ${num(total)} county-and-month records. ${num(difficult)} of them (${pct(difficult / total)}) came out hard to hedge under every single setting: for those, no choice among the listed stations can be expected to remove much of the risk. ${num(ambiguous)} (${pct(ambiguous / total)}) changed answer depending on the setting, and the remaining ${num(positive)} (${pct(positive / total)}) were never flagged as hard to hedge.`
    : 'No classification counts are recorded.';
  return article(key, [
    lead('Some counties are simply too far, in weather terms, from any of the thirteen listed stations. This is a national screen for those places: where does basis risk stay high no matter how the screen is set up?'),
    statusCallout(record),
    heading('What the screen found'),
    para(answer),
    total ? tiles([
      tile('Hard to hedge every time', num(difficult), `${pct(difficult / total)} of screened records`),
      tile('Depends on the setting', num(ambiguous), `${pct(ambiguous / total)} of screened records`),
      tile('Never flagged as hard', num(positive), `${pct(positive / total)} of screened records`),
      tile('Settings tried', num(experiment.settings), 'each run over the same records'),
    ]) : null,
    para(`Outcome: ${dispositionText(experiment.disposition).toLowerCase()}.`),
    para(`What this covers: ${PROTOCOL_TEXT[String(payload.limitations || experiment.scope || '')] || plainScope(payload.limitations || experiment.scope || '')} The counts describe the records the screen was run over, not every county-and-month in the atlas.`, 'note'),
    ...recordFooter(record, payload, countyFor, [['Registration record', experiment.protocol_id]]),
  ]);
}

/* ---------- Case studies ---------- */
/** The five-county hedge table, built from the public county objects (the same ones Explore shows). */
function nebraskaHedgeTables({ loadObject, countyFor, pageLink }) {
  const holder = node('div', undefined, { class: 'stack' });
  holder.append(para('Loading the five county records…', 'status'));
  const load = async (fips, pair) => { try { return { fips, record: await loadObject(`county:${fips}:${pair}`) }; } catch (error) { return { fips, message: error.message }; } };
  Promise.all(NEBRASKA_PAIRS.map(async (pair) => ({ pair, rows: await Promise.all(NEBRASKA_FIPS.map((fips) => load(fips, pair))) }))).then((sets) => {
    const parts = [];
    const facts = (entry) => {
      if (!entry.record || entry.record.status !== 'available') return null;
      const payload = entry.record.payload || {}; const matched = payload.matched_policy || {}; const asof = payload.selection_asof || {}; const interval = matched.interval || {};
      const alternatives = Array.isArray(payload.alternatives) ? payload.alternatives : [];
      const nearest = [...alternatives].sort((a, b) => (a.distance_km ?? Infinity) - (b.distance_km ?? Infinity))[0];
      const selected = asof.station_id || asof.station_name || null;
      const nearestId = nearest ? (nearest.station_id || nearest.station_name) : null;
      const selectedMeta = alternatives.find((item) => item.station_id === asof.station_id || item.station_name === asof.station_name);
      return { station: selected, he: matched.metric?.value, delta: matched.delta_he, low: interval.low, high: interval.high, nearestHe: matched.nearest_he, nearest: nearestId, nearestKm: nearest?.distance_km, selectedKm: selectedMeta?.distance_km, sameAsNearest: Boolean(selected && nearestId && String(selected) === String(nearestId)), seasons: matched.common_seasons, n: matched.n_common, stability: matched.selection_stability };
    };
    sets.forEach(({ pair, rows }) => {
      parts.push(heading(pairLabel(pair)));
      const tableRows = rows.map((entry) => {
        const name = countyName(entry.fips, countyFor); const others = NEBRASKA_FIPS.filter((fips) => fips !== entry.fips);
        const links = node('span', undefined, { class: 'cell-links' });
        /* Two stacked links; the separator that used to sit between them became its own flex row. */
        links.append(
          node('a', 'Explore', { href: pageLink('index.html', { fips: entry.fips, indexId: pair }), 'aria-label': `Open ${name}, ${pairLabel(pair)}, in Explore` }),
          node('a', 'Compare', { href: pageLink('compare.html', { fips: entry.fips, comparisonFips: others.join(','), indexId: pair }), 'aria-label': `Open ${name} with the other four counties in Compare, ${pairLabel(pair)}` }),
        );
        const fact = facts(entry);
        if (!fact) { const row = [name, NA, NA, NA, links]; row.__class = 'is-muted'; return row; }
        const gain = stacked(finite(fact.delta) ? pts(fact.delta) : NA, finite(fact.low) && finite(fact.high) ? rangeText(fact.low, fact.high, pts) : null);
        const station = stacked(fact.station ? stationCity(fact.station) : NA, finite(fact.selectedKm) ? `${km(fact.selectedKm)} away${fact.sameAsNearest ? ' · also the nearest' : ''}` : null);
        const seasons = Array.isArray(fact.seasons) && fact.seasons.length ? `over ${num(fact.n ?? fact.seasons.length)} seasons, ${seasonRange(fact.seasons)}` : (finite(fact.n) ? `over ${num(fact.n)} seasons` : null);
        const row = [name, station, stacked(pct(fact.he), seasons), gain, links];
        if (entry.fips === POOR_HEDGE_FIPS) row.__class = 'is-flagged';
        return row;
      });
      parts.push(dataTable(['County', 'Station selected for 2026', 'Hedge effectiveness', 'Gain vs nearest station', 'Open'], tableRows, { numeric: [2, 3] }));
      const all = node('p', undefined, { class: 'note' });
      all.append(fragment(['Side by side: ', node('a', `open all five counties in Compare for ${pairLabel(pair)}`, { href: pageLink('compare.html', { fips: NEBRASKA_FIPS[0], comparisonFips: NEBRASKA_FIPS.slice(1).join(','), indexId: pair }) }), '.']));
      parts.push(all);
    });
    parts.push(para('"Station selected for 2026" is the listed station the atlas picks for this county under the prior-best rule, exactly as the Explore map shows it, with its distance from the county. Hedge effectiveness is the share of the county\'s year-to-year variation the rule removed, measured over the seasons named beneath it. Gain vs nearest station compares that rule with always taking the nearest listed station, in percentage points, with its 95% range underneath; a negative gain means the nearest station would have hedged better. Because the rule can pick a different station at each past decision point, a county whose 2026 pick happens to be the nearest station can still show a gain that is not zero. The highlighted row is Scotts Bluff, the poor-hedge case discussed below.', 'note'));
    const poor = sets.map(({ pair, rows }) => ({ pair, fact: facts(rows.find((entry) => entry.fips === POOR_HEDGE_FIPS) || {}) })).filter((item) => item.fact && finite(item.fact.he));
    if (poor.length) {
      /* Lead with the month this county is hedged worst in, which is what makes it the poor-hedge case. */
      const worst = [...poor].sort((a, b) => Number(a.fact.he) - Number(b.fact.he))[0]; const other = poor.find((item) => item !== worst);
      const pieces = [`${countyName(POOR_HEDGE_FIPS, countyFor)}, at the western end of the state, is the poor-hedge case. The closest listed station to it is ${worst.fact.nearest ? stationCity(worst.fact.nearest) : 'over a thousand kilometres away'}${finite(worst.fact.nearestKm) ? `, ${km(worst.fact.nearestKm)} away` : ''}, so there is no local index to fall back on. For ${pairLabel(worst.pair)} the prior-best rule removed ${pct(worst.fact.he)} of the county's year-to-year variation`];
      if (finite(worst.fact.delta) && Number(worst.fact.delta) < 0) pieces.push(`, against ${pct(worst.fact.nearestHe)} for always taking the nearest station: ${pointsText(worst.fact.delta)} worse`);
      if (finite(worst.fact.low) && finite(worst.fact.high)) pieces.push(`; the 95% band runs from ${pts(worst.fact.low)} to ${pts(worst.fact.high)}, so the shortfall is not separated from zero, but nothing supports the rule here either`);
      pieces.push('.');
      if (other) pieces.push(` For ${pairLabel(other.pair)} the rule removed only ${pct(other.fact.he)} of the county's variation.`);
      pieces.push(' Whichever listed station is used, most of this county\'s weather risk stays unhedged. It is the case the basket and next-station studies were designed around.');
      parts.push(heading('The poor-hedge case'), para(pieces.join('')));
    }
    const failed = sets.flatMap(({ rows }) => rows.filter((entry) => entry.message));
    if (failed.length) parts.push(para(`${num(failed.length)} county record${failed.length === 1 ? '' : 's'} could not be loaded: ${failed[0].message}`, 'callout callout-warn'));
    holder.replaceChildren(...parts);
  });
  return holder;
}
function renderNebraska(key, record, context) {
  const { countyFor, pageLink, select } = context;
  const payload = record.payload || {}; const caseData = payload.case || {}; const mapping = Array.isArray(caseData.mapping) ? caseData.mapping : [];
  const rows = mapping.map((row) => {
    const link = node('a', countyLabel(countyFor?.(row.fips), row.fips) || row.county || NA, { href: pageLink('index.html', { fips: row.fips }) });
    return [link, row.place || NA, stationLabel(row.station)];
  });
  const recordLink = (label, target) => { const control = node('button', label, { type: 'button', class: 'linklike' }); control.addEventListener('click', () => select(target, true)); return control; };
  const actions = node('p', undefined, { class: 'record-actions' });
  actions.append(fragment([
    'These same five counties are the evidence behind three studies in this library: the ',
    recordLink('station-basket study (R02)', 'research:r02'), ', the ',
    recordLink('joint-book study (R03)', 'research:r03'), ' and the ',
    recordLink('next-station pilot', 'research:next_station'),
    '. The forward-looking Nebraska books are in the ',
    node('a', 'Portfolio Lab', { href: pageLink('portfolio.html') }), '.',
  ]));
  return article(key, [
    lead('Five Nebraska counties, each with a nearby airport weather station, form the test bed for the basket, joint-book and next-station studies. None of the five airports has a listed contract, so the first question is how well the thirteen listed stations hedge these counties at all.'),
    statusCallout(record),
    caseData.interpretation ? para(interpretationText(caseData.interpretation)) : null,
    caseData.scope ? para(`What the case covers: ${PROTOCOL_TEXT[String(caseData.scope)] || plainScope(caseData.scope)}.`) : null,
    heading('How the listed stations hedge these counties'),
    nebraskaHedgeTables(context),
    heading('The nearby airports used in the case studies'),
    para('These five airports have long public temperature records but no listed contract. They stand in for a local index that does not exist, and are never presented as tradable.'),
    rows.length ? dataTable(['County', 'Place', 'Nearby airport (not listed)'], rows) : para('No county mapping is recorded.', 'note'),
    payload.limitations ? para('Everything here compares county weather with station weather over past seasons. No price, premium or market value is involved.', 'note') : null,
    node('h4', 'Where this case is used'),
    actions,
    ...recordFooter(record, payload, countyFor, [['Registration record', caseData.protocol_id]]),
  ]);
}

function renderNextStation(key, record, { countyFor }) {
  const payload = record.payload || {}; const casePage = payload.case_page_payload || {}; const rules = payload.adjudication || {};
  const summary = Array.isArray(payload.objective_summary) ? payload.objective_summary : []; const base = summary.filter((row) => row.sensitivity === 'base'); const zeroFee = summary.filter((row) => row.sensitivity === 'zero_fee');
  const pick = (strategy, objective) => base.find((row) => row.strategy === strategy && row.objective === objective);
  const selectedEs = pick('training_selected_one_addition', 'es'); const selectedVar = pick('training_selected_one_addition', 'variance'); const baselineEs = pick('baseline', 'es');
  const minimum = rules.minimum_paired_origins;
  const meets = selectedEs && selectedVar && finite(minimum) && selectedEs.paired_gain?.ci95?.[0] > 0 && selectedVar.paired_gain?.ci95?.[0] > 0 && selectedEs.paired_origins >= minimum && selectedVar.paired_origins >= minimum;
  const disagreement = payload.variance_vs_es_disagreement || {};
  const perOrigin = (Array.isArray(disagreement.per_origin) ? disagreement.per_origin : []).filter((row) => row && finite(row.origin)).sort((a, b) => Number(a.origin) - Number(b.origin));
  const chosen = new Map(); perOrigin.forEach((row) => { if (row.es_addition) chosen.set(row.es_addition, (chosen.get(row.es_addition) || 0) + 1); });
  const chosenText = [...chosen.entries()].sort((a, b) => b[1] - a[1]).map(([station, times]) => `${stationCity(station)} ${num(times)} times`);
  let recent = null;
  if (perOrigin.length && perOrigin.at(-1).es_addition) { const last = perOrigin.at(-1).es_addition; let run = 0; for (let index = perOrigin.length - 1; index >= 0 && perOrigin[index].es_addition === last; index -= 1) run += 1; recent = { station: last, run, from: perOrigin[perOrigin.length - run].origin, to: perOrigin.at(-1).origin }; }
  const originsText = perOrigin.length ? ` (${rangeText(perOrigin[0].origin, perOrigin.at(-1).origin, yearText)})` : '';
  const uncertainty = payload.uncertainty || {};
  const answer = [];
  if (selectedEs && baselineEs) {
    answer.push(`Yes, on this evidence. Across ${num(selectedEs.paired_origins)} decision points${originsText}, letting the training data pick one extra Nebraska station each time lowered the book's worst-case cost — the average of the worst tenth of outcomes, written ES90 — from ${money(baselineEs.mean_deterministic_cost)} for the book with no addition to ${money(selectedEs.mean_deterministic_cost)} with it.`);
    answer.push(`Scored decision point by decision point and then averaged, the gain over the plain book was ${money(selectedEs.paired_gain?.gain)}, with a 95% band of ${intervalText(selectedEs.paired_gain?.ci95, money)}${finite(uncertainty.resamples) ? ` built by resampling whole decision points ${num(uncertainty.resamples)} times` : ''}. That paired figure is not the difference between the two averages above, because each decision point is compared with itself rather than with the overall mean.`);
  }
  if (chosenText.length) answer.push(`Across those ${num(perOrigin.length)} decision points the station the training data picked was ${listText(chosenText)}${recent && recent.run > 1 ? `, and ${stationCity(recent.station)} at every point from ${yearText(recent.from)} to ${yearText(recent.to)}` : ''}.`);
  if (selectedVar) answer.push(`Judged by how much the addition steadied the book's cost from year to year, rather than by its worst outcomes, the gain was ${selectedVar.paired_gain?.ci95?.[0] > 0 ? 'also clear of zero at the lower end of its band' : 'not clear of zero at the lower end of its band'}.`);
  if (selectedEs && selectedVar) answer.push(meets ? `Both bands stay above zero and ${num(selectedEs.paired_origins)} paired points clear the registered minimum of ${num(minimum)}, so the rule for keeping this as a research feature is met.` : 'The registered rule for keeping this as a research feature was not met on these figures.');
  answer.push(`Under the rules registered before the study ran, the reading is: ${dispositionText(payload.disposition || casePage.disposition).toLowerCase()}.`);
  if (finite(disagreement.common_scored_origins)) answer.push(`The two ways of measuring risk picked the same station at ${num(disagreement.same_addition_origins)} of the ${num(disagreement.common_scored_origins)} decision points they both scored, and disagreed at ${num(disagreement.different_addition_origins)}.`);
  const caveat = sentence([node('strong', 'Read the band as descriptive. '), `The decision points are consecutive years of real weather, so they are not independent draws. The band says how much the gain moved when whole decision points were resampled${uncertainty.note ? ` (in the record's own words, "${uncertainty.note}")` : ''}. It is not the chance that a future season shows the same gain.`], 'callout');
  const ruleRows = ['promote_rule', 'retain_research_rule', 'inconclusive_rule', 'stop_missing_evidence_rule'].filter((field) => rules[field]).map((field) => [RULE_TEXT[field][0], RULE_TEXT[field][1]]);
  const registeredRules = ruleRows.length ? node('details', undefined, { class: 'plain' }) : null;
  if (registeredRules) registeredRules.append(node('summary', 'The rules as registered, word for word'), dataTable(['Outcome', 'Registered wording'], ['promote_rule', 'retain_research_rule', 'inconclusive_rule', 'stop_missing_evidence_rule'].filter((field) => rules[field]).map((field) => [RULE_TEXT[field][0], rules[field]])));
  const admission = Array.isArray(payload.admission_table) ? payload.admission_table : (casePage.station_map || []);
  const distinct = (field, map = (value) => value) => [...new Set(admission.map((row) => row[field]).filter(Boolean))].map(map);
  const roles = distinct('registry_role', (value) => ROLE_TEXT[value] || humanize(value)); const statuses = distinct('admission_status', (value) => ADMISSION_TEXT[value] || humanize(value)); const disclosures = distinct('availability_disclosure');
  const uniform = admission.length > 0 && roles.length <= 1 && statuses.length <= 1 && disclosures.length <= 1;
  const admissionIntro = uniform ? para(`Every station in the table is treated the same way — ${roles[0] || NA} stations, still awaiting their per-decision-point quality checks — and none of them carries any claim of being available to trade.`) : null;
  const admissionHeaders = uniform ? ['Station', 'Name in the NOAA record', 'Elevation', 'Latitude, longitude', 'Source'] : ['Station', 'Name in the NOAA record', 'Role', 'Admission status', 'Availability', 'Elevation', 'Latitude, longitude', 'Source'];
  const admissionRows = admission.map((row) => {
    const common = [stationLabel(row.station_id || row.name), row.name ? titleCase(row.name) : NA];
    const detail = uniform ? [] : [ROLE_TEXT[row.registry_role] || humanize(row.registry_role), ADMISSION_TEXT[row.admission_status] || humanize(row.admission_status), row.availability_disclosure || NA];
    const source = row.source_operational?.source_url ? externalLink('NOAA record', row.source_operational.source_url) : null;
    if (source) source.className = 'nowrap';
    return [...common, ...detail, finite(row.elevation_m) ? `${num(row.elevation_m)} m` : NA, `${num(row.latitude, 3)}, ${num(row.longitude, 3)}`, source || NA];
  });
  const resultTable = (rows, objective) => {
    const subset = rows.filter((row) => row.objective === objective); if (!subset.length) return [];
    const isMoney = objective === 'es'; const fmt = isMoney ? money : (v) => count(v);
    return [dataTable(
      ['Book', 'Mean cost per season', isMoney ? 'Gain vs plain book' : 'Steadying gain', '95% band', 'Decision points'],
      subset.map((row) => {
        /* The plain book is what every gain is measured against, so its own gain is zero by construction:
           printing "$0" and a "$0 to $0" band would read as a result rather than as the reference line. */
        const reference = row.strategy === 'baseline';
        const line = [strategyText(row.strategy), money(row.mean_deterministic_cost), reference ? '—' : fmt(row.paired_gain?.gain), reference ? '—' : intervalText(row.paired_gain?.ci95, fmt), num(row.paired_origins)];
        if (row.strategy === 'baseline') line.__class = 'is-muted';
        if (row.strategy === 'training_selected_one_addition') line.__class = 'is-selected';
        return line;
      }), { numeric: [1, 2, 3, 4] },
    )];
  };
  const varianceDetails = base.some((row) => row.objective === 'variance') ? node('details', undefined, { class: 'plain' }) : null;
  if (varianceDetails) {
    varianceDetails.append(node('summary', 'The same comparison judged on steadiness instead of worst outcomes'));
    varianceDetails.append(para('This version scores each book by how much its cost varies from year to year rather than by its worst seasons. The gains are in squared dollars, so their size cannot be read as money — only the sign and whether the band clears zero are meaningful. The costs in the first column are still dollars per season.', 'note'), ...resultTable(base, 'variance'));
  }
  const zeroFeeDetails = zeroFee.length ? node('details', undefined, { class: 'plain' }) : null;
  if (zeroFeeDetails) zeroFeeDetails.append(node('summary', 'If the extra station cost nothing to add'), para('The same comparison with the assumed cost of adding a station set to zero.', 'note'), ...resultTable(zeroFee, 'es'), ...resultTable(zeroFee, 'variance'));
  return article(key, [
    lead('Which one additional Nebraska airport, if any, would have made a five-county January heating book less risky? The candidates are airports with no listed contract, so nothing here could have been traded; the pilot asks only whether adding one to the book would have helped, decision point by decision point.'),
    statusCallout(record),
    heading('What the pilot found'),
    ...answer.map((text) => para(text)),
    caveat,
    Array.isArray(payload.consumed_development_years) && payload.consumed_development_years.length ? para(`The seasons ${seasonRange(payload.consumed_development_years)} were already used while building the studies, so they are not an untouched test.`, 'note') : null,
    heading('How the pilot decides'),
    finite(minimum) ? para(`A comparison counts only if at least ${num(minimum)} decision points could be scored on both sides. What happens then depends on where the 95% bands fall:`) : null,
    ruleRows.length ? kvTable(ruleRows) : null,
    registeredRules,
    heading('Book by book'),
    ...(base.length ? resultTable(base, 'es') : [para('No results are recorded.', 'note')]),
    para('Costs and gains are dollars per season, averaged over the decision points scored. A positive gain means that book cost less than the plain five-county book on the same decision points. The highlighted row is the one the pilot reports; the greyed row is the plain book everything else is measured against, so it has no gain of its own.', 'note'),
    varianceDetails,
    zeroFeeDetails,
    heading('The five airports in the pilot'),
    admissionIntro,
    admissionRows.length ? dataTable(admissionHeaders, admissionRows, { numeric: [admissionHeaders.indexOf('Elevation')] }) : para('No admission table is recorded.', 'note'),
    payload.supersedes?.reason ? para('An earlier version of this study was replaced. It demanded a complete January record for every station in every earlier season, which was stricter than the registered rule of twenty usable seasons and shut out stations that should have qualified. The recorded reason is under "All reported fields".', 'note') : null,
    payload.scope ? para('This is a backward-looking study of stations that stand in for indexes that do not exist. It makes no claim that a contract on any of these airports exists, could be listed, would find buyers, or could be traded.', 'note') : null,
    para('The question as registered, word for word, is kept under "All reported fields" with everything else the release recorded.', 'note'),
    ...recordFooter(record, payload, countyFor, [['Registration record', payload.protocol_id], ['Experiment', payload.experiment], ['Replaces', payload.supersedes?.artifact_id]]),
  ]);
}

/* ---------- Validation ---------- */
function periodText(value) {
  const text = String(value || '');
  const range = /^(\d{4})-(\d{2})\s+through\s+(\d{4})-(\d{2})$/.exec(text);
  if (range) return monthRange(`${range[1]}-${range[2]}`, `${range[3]}-${range[4]}`);
  return LEDGER_TEXT[text] || (text ? text : NA);
}
function renderHoldout(key, record, { countyFor }) {
  const payload = record.payload || {}; const ledger = Array.isArray(payload.access_ledger) ? payload.access_ledger : [];
  return article(key, [
    lead('A result is only a real test if it is measured on seasons that were never looked at while the method was being built. This record says which seasons have already been used, and which are still untouched.'),
    statusCallout(record),
    ledger.length ? dataTable(['Seasons', 'How they have been used', 'What that means'], ledger.map((row) => [periodText(row.period), LEDGER_TEXT[String(row.status)] || humanize(row.status), LEDGER_TEXT[String(row.interpretation)] || String(row.interpretation || NA)])) : para('No entries are recorded.', 'note'),
    para('Because the most recent three seasons were used during development, no result on this site can be read as an out-of-sample test of the method. A clean test needs seasons registered in advance and left alone until they have happened.', 'note'),
    payload.scoreability ? para('If a station\'s outcome is missing at one of these decision points, the rule simply cannot be scored there. A missing outcome never changes the choice that was made at the time.') : null,
    ...recordFooter(record, payload, countyFor),
  ]);
}

const TOPOLOGY_LABEL = { marginal: 'Each index on its own', dependence: 'How the indexes move together', downstream: 'What rests on what' };
function renderValidation(key, record, { countyFor }) {
  const payload = record.payload || {}; const topology = payload.topology || {}; const origins = Array.isArray(payload.r04_origins) ? payload.r04_origins : [];
  const order = ['marginal', 'dependence', 'downstream'];
  const rows = Object.entries(topology).sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0])).map(([name, text]) => [TOPOLOGY_LABEL[name] || fieldLabel(name, countyFor), TOPOLOGY_TEXT[String(text)] || String(text)]);
  const notes = origins.filter((row) => row.unavailable_reason).map((row) => `${yearText(row.origin)}: ${REASON_TEXT[row.unavailable_reason] || statusText(row.unavailable_reason)}`);
  return article(key, [
    lead('How the pieces of evidence on this site fit together, what each one may be used for, and why a simulated season never counts as an extra year of history.'),
    statusCallout(record),
    para('The number of real years is the hard limit on everything published here. Simulating two thousand seasons produces two thousand versions of the same fitted model, not two thousand new observations, so a study with two decision points still has two decision points however many paths it prices against.'),
    rows.length ? heading('What the evidence checks') : null,
    rows.length ? kvTable(rows) : null,
    heading('Where the generator comparison could be scored'),
    origins.length ? dataTable(['Decision point', 'Fitted with data up to', 'Scored', 'Common-year trend', 'Two-stage daily generator'], origins.map((row) => { const line = [yearText(row.origin), dateShort(row.fit_cutoff), scoredText(row.scoreability), count(row.common_year_mean_crps, 1), count(row.r2j_mean_crps, 1)]; if (row.unavailable_reason) line.__class = 'is-muted'; return line; }), { numeric: [0, 3, 4] }) : null,
    para('Distance between the simulated spread of outcomes and what actually happened, in degree days; lower is closer. The release calls it the mean CRPS.', 'note'),
    notes.length ? para(notes.join(' '), 'note') : null,
    ...recordFooter(record, payload, countyFor),
  ]);
}

function renderPerformance(key, record, { countyFor }) {
  const payload = record.payload || {}; const origins = Array.isArray(payload.origins) ? payload.origins : [];
  const scored = origins.filter((row) => row.scoreability === 'complete');
  return article(key, [
    lead('What one rebuild of the weather-generator comparison took on an ordinary machine, decision point by decision point: how many series were scored at once, how long it ran and how much memory it needed.'),
    statusCallout(record),
    para('These are the measured timings of the runs behind the generator comparison. They describe those runs only, and are not a claim about how the study would scale to the whole country.'),
    tiles([
      tile('Most memory used', bytesText(payload.peak_rss_bytes), 'high-water mark across the scored runs'),
      tile('Decision points', num(origins.length), `${num(scored.length)} of them could be scored`),
    ]),
    origins.length ? dataTable(['Decision point', 'Series scored at once', 'Time to run', 'Memory used', 'Scored'], origins.map((row) => [yearText(row.origin), count(row.columns), secondsText(row.runtime_seconds), bytesText(row.peak_rss_bytes), row.scoreability ? scoredText(row.scoreability) : 'No']), { numeric: [0, 1, 2, 3] }) : null,
    origins.length > scored.length ? para(`One row per decision point. Nothing was measured for the ${listText(origins.filter((row) => row.scoreability !== 'complete').map((row) => yearText(row.origin)))} decision point, because the comparison could not be scored there.`, 'note') : null,
    ...recordFooter(record, payload, countyFor, [['Producer', payload.r04_producer]]),
  ]);
}

/* ---------- This release ---------- */
function renderReleases(key, record, { countyFor, bootstrap }) {
  const payload = record.payload || {}; const sources = Array.isArray(payload.source_artifact_ids) ? payload.source_artifact_ids : [];
  const { source_artifact_ids: omitted, ...rest } = payload;
  const provenance = provenanceBlock([
    ['Release', record.release_id],
    ['Release lock', payload.release_lock],
    ['Bundle inventory', payload.verified_bundle_inventory],
    ['Schema version', payload.schema_version],
    ['Data vintage', record.data_vintage_id],
    ['Valuation date', record.valuation_asof],
    ['Result object', record.object_id],
    [`Input files (${num(sources.length)})`, sources.join(', ')],
  ], { summary: 'Full release identifier and the list of input files' });
  const links = node('div', undefined, { class: 'link-row record-actions' });
  links.append(externalLink('Source code and data on GitHub', REPO_URL), node('a', 'The V1 archive of this site', { href: '../v1/index.html' }));
  return article(key, [
    lead('Every page on this site reads from one fixed release: a bundle of pre-computed results that cannot change once published. This record identifies it and lists the files it was built from.'),
    statusCallout(record),
    kvTable([
      ['This release', releaseLabel(record.release_id)],
      ['Valued as of', dateShort(record.valuation_asof || bootstrap?.defaults?.valuation_asof)],
      ['Results it contains', finite(bootstrap?.object_count) ? num(bootstrap.object_count) : num(bootstrap?.objects?.length)],
      ['Input files', num(sources.length)],
      ['How it was built', payload.release_policy ? (POLICY_TEXT[String(payload.release_policy)] || `The ${payload.release_policy}.`) : NA],
    ]),
    para('The name above is the first eight characters of a long identifier that stands for the exact contents of this release: change one number anywhere and the identifier changes too. The full form, and the fingerprint of every input file, are in the block below — the only place on the site where they are written out. Every other record in this library carries the short form.'),
    provenance,
    heading('Elsewhere'),
    links,
    ...recordFooter(record, rest, countyFor),
  ]);
}

function renderGeneric(key, record, { countyFor }) {
  const swept = []; const payload = sweepIdentifiers(record.payload || {}, '', countyFor, swept) ?? {};
  return article(key, [
    lead('A record published with this release that has no page of its own. Everything it holds is listed below, with field names spelled out.'),
    statusCallout(record),
    Object.keys(payload).length ? structured('', payload, 0, countyFor) : para('No fields beyond identifiers are recorded.', 'note'),
    recordProvenance(record, swept),
  ]);
}

const RENDERERS = {
  'research:glossary': renderGlossary, 'research:limitations': renderLimitations, 'research:source_support': renderSources, 'research:data': renderSources, 'research:method': renderMethod,
  'research:r01': renderR01, 'research:r02': renderR02, 'research:r03': renderR03, 'research:r04': renderR04, 'research:r05': renderR05,
  'research:nebraska': renderNebraska, 'research:next_station': renderNextStation, 'research:holdout': renderHoldout, 'research:validation': renderValidation, 'research:performance': renderPerformance, 'research:releases': renderReleases,
};
function renderRecord(key, record, context) { return (RENDERERS[key] || renderGeneric)(key, record, context); }

/* ---------- mount ---------- */
export function mountResearch({ bootstrap, loadObject, scenario, setScenario, pageLink, countyFor }) {
  const references = bootstrap.objects.filter((object) => ['research', 'research_evidence'].includes(object.result_type));
  const keys = [ABOUT_KEY, ...references.map((reference) => reference.object_key || reference.object_id)];
  const shell = node('div', undefined, { class: 'doc-shell' });
  const toc = node('nav', undefined, { class: 'doc-toc', 'aria-label': 'Research records' });
  const toggle = node('button', undefined, { type: 'button', class: 'toc-toggle', 'aria-expanded': 'false', 'aria-controls': 'research-toc-list' });
  const currentLabel = node('span', 'Choose a record', { class: 'toc-current' }); const toggleState = node('span', 'Show', { class: 'toc-state' });
  toggle.append(node('span', 'Contents', { class: 'toc-label' }), currentLabel, toggleState);
  const list = node('div', undefined, { class: 'toc-list', id: 'research-toc-list' });
  toc.append(toggle, list);
  const body = node('div', undefined, { class: 'doc-body', 'aria-live': 'polite' });
  shell.append(toc, body);
  const panel = replacePanel('.lab-panel', [shell]);
  if (!panel) return;
  const setOpen = (open) => { shell.classList.toggle('toc-open', open); toggle.setAttribute('aria-expanded', String(open)); toggleState.textContent = open ? 'Hide' : 'Show'; };
  toggle.addEventListener('click', () => setOpen(!shell.classList.contains('toc-open')));
  const buttons = new Map(); const cache = new Map();
  let selected = scenario.researchRecord; let token = 0;
  const context = { countyFor, pageLink, bootstrap, loadObject, select: (key, user) => select(key, user) };

  /** `mode` is the history mode handed to setScenario: the automatic first selection replaces the landing entry
   *  so the browser's Back button still leaves the page; user choices push as before. */
  async function select(key, userInitiated = false, mode = undefined) {
    const button = buttons.get(key); if (!button) return;
    buttons.forEach((item, itemKey) => { if (itemKey === key) item.setAttribute('aria-current', 'true'); else item.removeAttribute('aria-current'); });
    currentLabel.textContent = recordMeta(key).toc;
    if (userInitiated) setOpen(false);
    if (selected !== key) { selected = key; setScenario({ researchRecord: key }, mode); }
    const request = ++token;
    const finish = (content) => {
      if (request !== token) return;
      body.replaceChildren(content);
      if (userInitiated) { const title = body.querySelector('h3'); if (title) title.focus({ preventScroll: true }); if (window.innerWidth < 900) body.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
    };
    if (key === ABOUT_KEY) { finish(renderAbout(context)); return; }
    body.replaceChildren(para('Loading this record…', 'status'));
    try {
      if (!cache.has(key)) cache.set(key, loadObject(key));
      const record = await cache.get(key);
      finish(renderRecord(key, record, context));
    } catch (error) {
      cache.delete(key);
      const message = node('p', undefined, { class: 'callout callout-warn', role: 'alert' });
      message.append(node('strong', 'This record could not be loaded. '), document.createTextNode(error.message));
      finish(message);
    }
  }

  const groups = new Map();
  keys.forEach((key) => { const group = recordMeta(key).group; if (!groups.has(group)) groups.set(group, []); groups.get(group).push(key); });
  const known = Object.keys(RECORDS);
  const order = (key) => (known.includes(key) ? known.indexOf(key) : known.length + keys.indexOf(key));
  [...groups.keys()].sort((a, b) => GROUP_ORDER.indexOf(a) - GROUP_ORDER.indexOf(b)).forEach((group) => {
    list.append(node('div', group, { class: 'toc-group', role: 'presentation' }));
    groups.get(group).sort((a, b) => order(a) - order(b)).forEach((key) => {
      const button = node('button', recordMeta(key).toc, { type: 'button', 'data-record': key });
      button.addEventListener('click', () => select(key, true));
      buttons.set(key, button); list.append(button);
    });
  });

  if (!references.length) body.append(para('No research records are published for this release.', 'callout callout-warn'));
  const requested = scenario.researchRecord;
  if (requested && !buttons.has(requested)) {
    const message = node('p', undefined, { class: 'callout callout-warn', role: 'alert' });
    message.append(node('strong', 'That record is not in this release. '), document.createTextNode('The link you followed asks for a record this release does not publish. Everything it does publish is listed under Contents; the introduction is below.'));
    body.append(message, renderAbout(context));
    return;
  }
  select(requested || ABOUT_KEY, false, 'replaceState');
}
