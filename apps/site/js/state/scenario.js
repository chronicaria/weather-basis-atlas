/** Versioned, public portion of the V2 workbench state. */
export const SCENARIO_VERSION = '2';
export const DEFAULT_SCENARIO = Object.freeze({
  version: SCENARIO_VERSION,
  schemaVersion: '2.0',
  releaseId: null,
  route: 'explore',
  fips: '31109',
  comparisonFips: null,
  indexId: 'HDD-01',
  contractStart: '2027-01-01',
  contractEnd: '2027-01-31',
  valuationAsOf: '2026-07-01',
  payoffFamily: 'put',
  direction: 'long',
  strike: null,
  secondaryStrike: null,
  payoffStructure: 'monthly_option',
  contractMembers: null,
  contractScenarioSetId: null,
  assumedLoad: null,
  cap: null,
  multiplier: null,
  strategy: 'nearest_eligible',
  assumptions: 'public-fixture',
});

const keys = {
  version: 'v', schemaVersion: 'schema', releaseId: 'release', route: 'route', fips: 'fips', comparisonFips: 'compare', indexId: 'index',
  contractStart: 'start', contractEnd: 'end', valuationAsOf: 'asof',
  payoffFamily: 'payoff', direction: 'side', strike: 'strike', secondaryStrike: 'strike2', payoffStructure: 'structure', contractMembers: 'members', contractScenarioSetId: 'contractSet', assumedLoad: 'load', cap: 'cap',
  multiplier: 'multiplier', strategy: 'strategy', assumptions: 'assumptions',
};
const finiteOrNull = (value) => value === null || value === '' || value === undefined
  ? null : Number.isFinite(Number(value)) ? Number(value) : null;
const textOr = (value, fallback) => typeof value === 'string' && value.trim() ? value.trim() : fallback;

export function normalizeScenario(input = {}) {
  const value = { ...DEFAULT_SCENARIO, ...input, version: SCENARIO_VERSION };
  return {
    ...value,
    releaseId: typeof value.releaseId === 'string' && value.releaseId.trim() ? value.releaseId.trim() : null,
    schemaVersion: value.schemaVersion === '2.0' ? '2.0' : DEFAULT_SCENARIO.schemaVersion,
    route: ['explore', 'compare', 'contract', 'portfolio', 'research'].includes(value.route) ? value.route : DEFAULT_SCENARIO.route,
    fips: /^\d{5}$/.test(String(value.fips)) ? String(value.fips) : DEFAULT_SCENARIO.fips,
    comparisonFips: String(value.comparisonFips || '').split(',').filter((fips) => /^\d{5}$/.test(fips)).slice(0, 5).join(',') || null,
    indexId: /^[A-Z]+-\d{2}$/.test(String(value.indexId)) ? String(value.indexId) : DEFAULT_SCENARIO.indexId,
    contractStart: textOr(value.contractStart, DEFAULT_SCENARIO.contractStart),
    contractEnd: textOr(value.contractEnd, DEFAULT_SCENARIO.contractEnd),
    valuationAsOf: textOr(value.valuationAsOf, DEFAULT_SCENARIO.valuationAsOf),
    payoffFamily: ['linear', 'call', 'put', 'capped_call', 'capped_put', 'spread', 'collar'].includes(value.payoffFamily)
      ? value.payoffFamily : DEFAULT_SCENARIO.payoffFamily,
    payoffStructure: ['monthly_option', 'option_on_strip', 'sum_of_monthly_options'].includes(value.payoffStructure) ? value.payoffStructure : DEFAULT_SCENARIO.payoffStructure,
    contractMembers: typeof value.contractMembers === 'string' && /^[A-Z0-9:,_-]+$/.test(value.contractMembers) ? value.contractMembers : null,
    contractScenarioSetId: typeof value.contractScenarioSetId === 'string' && /^[A-Za-z0-9:._-]+$/.test(value.contractScenarioSetId) ? value.contractScenarioSetId : null,
    direction: ['long', 'short'].includes(value.direction) ? value.direction : DEFAULT_SCENARIO.direction,
    strike: finiteOrNull(value.strike), secondaryStrike: finiteOrNull(value.secondaryStrike), assumedLoad: finiteOrNull(value.assumedLoad), cap: finiteOrNull(value.cap), multiplier: finiteOrNull(value.multiplier),
    strategy: textOr(value.strategy, DEFAULT_SCENARIO.strategy),
    assumptions: textOr(value.assumptions, DEFAULT_SCENARIO.assumptions),
  };
}

export function decodeScenario(search = window.location.search) {
  const params = new URLSearchParams(search);
  if (!params.has('v')) return { scenario: { ...DEFAULT_SCENARIO }, error: null, legacy: Boolean(window.location.hash) };
  if (params.get('v') !== SCENARIO_VERSION) return { scenario: null, error: 'This link uses an unsupported scenario version.', legacy: false };
  const raw = Object.fromEntries(Object.entries(keys).map(([field, key]) => [field, params.get(key)]));
  return { scenario: normalizeScenario(raw), error: null, legacy: false };
}

export function encodeScenario(input) {
  const scenario = normalizeScenario(input);
  const params = new URLSearchParams();
  Object.entries(keys).forEach(([field, key]) => {
    const value = scenario[field];
    if (value !== null && value !== undefined && value !== '') params.set(key, String(value));
  });
  return `?${params.toString()}`;
}

export function scenarioLabel(scenario) {
  const s = normalizeScenario(scenario);
  return `${s.fips} · ${s.indexId} · ${s.contractStart} to ${s.contractEnd} · ${s.payoffFamily} ${s.direction}`;
}
