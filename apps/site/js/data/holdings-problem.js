/** Compile a published or local book using only its frozen aligned matrices. */
function rawMatrix(envelope) { return envelope?.payload?.matrix || envelope?.payload; }

function canonicalMatrix(envelope, label) {
  const matrix = rawMatrix(envelope); const scenarioSet = envelope?.payload?.scenario_set;
  if (!matrix || matrix.schema_version !== '2.0' || matrix.matrix_kind !== 'aligned' || matrix.missing_support_policy !== 'reject' || !matrix.parent_scenario_set_id || !matrix.scenario_id_hash || !matrix.entity_id_hash || !Array.isArray(matrix.scenario_ids) || !Array.isArray(matrix.entity_ids) || !Array.isArray(matrix.values)) throw new Error(`${label} is not a complete aligned ScenarioMatrix.`);
  if (!Array.isArray(matrix.shape) || matrix.shape[0] !== matrix.scenario_ids.length || matrix.shape[1] !== matrix.entity_ids.length || matrix.values.length !== matrix.shape[0]) throw new Error(`${label} does not match its declared shape.`);
  if (scenarioSet && scenarioSet.scenario_set_id !== matrix.parent_scenario_set_id) throw new Error(`${label} ScenarioSet identity does not match its matrix parent.`);
  return { scenario_set_id: matrix.parent_scenario_set_id, scenario_ids: matrix.scenario_ids, entity_ids: matrix.entity_ids, values: matrix.values, probability_weights: matrix.probability_weights || scenarioSet?.probability_weights || null };
}

function finite(value, label) { const number = Number(value); if (!Number.isFinite(number)) throw new Error(`${label} must be finite.`); return number; }

function canonicalCandidates(book, overrides) {
  const contracts = book?.candidate_contracts;
  const ids = overrides.candidate_ids || book?.candidate_ids || (contracts && !Array.isArray(contracts) ? Object.keys(contracts) : null);
  if (!ids || !Array.isArray(ids) || !ids.length) return [];
  if (new Set(ids).size !== ids.length) throw new Error('Candidate IDs must be unique and ordered.');
  const contractFor = (id) => Array.isArray(contracts) ? contracts.find((contract) => contract.candidate_id === id) : contracts?.[id];
  return ids.map(String).map((candidateId) => {
    const contract = contractFor(candidateId);
    if (!contract) throw new Error(`Published candidate ${candidateId} has no explicit frozen contract.`);
    const stationEntity = contract.station_entity_id || contract.entity_id;
    const payoff = contract.payoff || contract.payoff_kind;
    if (!stationEntity || !payoff) throw new Error(`Published candidate ${candidateId} lacks station entity or payoff kind.`);
    const multiplier = finite(contract.multiplier ?? contract.multiplier_usd_per_degree_day, `Candidate ${candidateId} multiplier`);
    const strike = finite(contract.strike, `Candidate ${candidateId} strike`);
    const cost = finite(book.candidate_unit_costs?.[candidateId], `Candidate ${candidateId} frozen unit cost`);
    return { row_id: `published-${candidateId}`, kind: 'hedge', candidate_id: candidateId, entity_id: stationEntity, unit_cost: cost * finite(overrides.cost_multiplier ?? 1, 'cost_multiplier'), payoff_spec: { ...contract, kind: payoff, strike, multiplier }, station_id: contract.station_id || String(stationEntity).split(':')[0], region_id: contract.region_id || String(stationEntity).split(':')[0] };
  });
}

function explicitCandidates(holdings, overrides) {
  const rows = holdings.filter((holding) => holding.candidate_id);
  if (!rows.length) return [];
  if (new Set(rows.map((row) => row.candidate_id)).size !== rows.length) throw new Error('Explicit hedge candidate IDs must be unique.');
  const multiplier = finite(overrides.cost_multiplier ?? 1, 'cost_multiplier');
  const byId = new Map(rows.map((row) => [row.candidate_id, row]));
  const selected = overrides.candidate_ids == null ? [...byId.keys()] : overrides.candidate_ids;
  if (!Array.isArray(selected) || new Set(selected).size !== selected.length || selected.some((id) => !byId.has(id))) throw new Error('Selected candidate IDs must be an ordered subset of explicit hedge rows.');
  return selected.map((candidateId) => {
    const holding = byId.get(candidateId);
    if (!holding.payoff_spec || !holding.entity_id) throw new Error(`Explicit hedge ${holding.row_id || holding.candidate_id} needs entity_id and payoff_spec.`);
    return { ...holding, unit_cost: finite(holding.unit_cost ?? 0, `Explicit hedge ${holding.candidate_id} unit cost`) * multiplier };
  });
}

export function compileHoldingsProblem({ book = {}, holdings = book.holdings || [], countyMatrices, stationMatrix, kernel, problem = {} }) {
  const station = canonicalMatrix(stationMatrix, 'Station scenarios');
  const counties = countyMatrices.map((envelope) => canonicalMatrix(envelope, 'County scenarios'));
  counties.forEach((county) => { if (county.scenario_set_id !== station.scenario_set_id || JSON.stringify(county.scenario_ids) !== JSON.stringify(station.scenario_ids)) throw new Error('County and station matrices do not share the exact scenario coordinates.'); });
  const entityIds = counties.flatMap((county) => county.entity_ids); if (new Set(entityIds).size !== entityIds.length) throw new Error('County scenario matrices repeat an entity ID.');
  const county = { scenario_set_id: station.scenario_set_id, scenario_ids: station.scenario_ids, entity_ids: entityIds, values: station.scenario_ids.map((_, row) => counties.flatMap((matrix) => matrix.values[row])) };
  const overrides = { ...(book.constraints || {}), ...problem };
  const exposures = holdings.filter((holding) => !holding.candidate_id).map((holding) => {
    const lossKind = holding.loss_kind || holding.kind;
    if (!['heating_shortfall', 'cooling_overrun', 'contract_payoff'].includes(lossKind)) throw new Error(`${holding.row_id || 'Exposure'} needs heating_shortfall, cooling_overrun, or contract_payoff loss_kind.`);
    if (lossKind === 'contract_payoff') {
      const structure = holding.payoff_structure;
      const members = structure === 'monthly_option' ? [holding.entity_id] : holding.member_entity_ids;
      if (!['monthly_option', 'option_on_strip', 'sum_of_monthly_options'].includes(structure) || !Array.isArray(members) || !members.length || members.length > 12 || new Set(members).size !== members.length || !members.every((entity) => /^\d{5}:(HDD|CDD)-\d{2}$/.test(entity))) throw new Error(`${holding.row_id || 'Contract claim'} needs a closed payoff structure with 1-12 exact FIPS:PAIR members.`);
      if (!holding.payoff_spec || !Number.isFinite(Number(holding.direction))) throw new Error(`${holding.row_id || 'Contract claim'} needs payoff_spec and finite direction.`);
      return { ...holding, kind: 'contract_payoff', loss_kind: 'contract_payoff', member_entity_ids: members };
    }
    return { ...holding, kind: lossKind, budget: holding.budget ?? holding.base, cap: holding.cap ?? holding.claim_cap_usd };
  });
  if (!exposures.length) throw new Error('A portfolio needs at least one exposure or claim row.');
  const countiesUsed = new Set(exposures.flatMap((holding) => holding.loss_kind === 'contract_payoff' ? holding.member_entity_ids : [holding.entity_id]).map((entity) => String(entity).split(':')[0]));
  if (countiesUsed.size > 6) throw new Error('Browser portfolio claims support at most six counties.');
  const hedges = explicitCandidates(holdings, overrides);
  const candidates = hedges.length ? hedges : canonicalCandidates(book, overrides);
  if (!candidates.length) throw new Error('No hedge candidates are declared. Import explicit hedge rows or select a published book with frozen candidate_contracts.');
  const inheritedWeights = problem.weights || book.probability_weights || station.probability_weights || undefined;
  const { candidate_ids, unit_costs, station_ids, region_ids, cost_multiplier, budget, ...constraints } = overrides;
  return kernel.compileHoldings({
    county_scenarios: county, station_scenarios: station, holdings: [...exposures, ...candidates],
    problem: { ...constraints, cash_budget: constraints.cash_budget ?? budget, scenario_type: book.scenario_type || 'physical_predictive', currency: book.currency || 'USD', weights: inheritedWeights, station_ids: candidates.map((candidate) => candidate.station_id || candidate.entity_id), region_ids: candidates.map((candidate) => candidate.region_id || candidate.station_id || candidate.entity_id) },
  });
}
