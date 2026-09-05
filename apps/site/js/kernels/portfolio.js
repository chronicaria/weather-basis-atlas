/* V2 finite portfolio kernel. Positive loss is adverse; a long payoff is beneficial. */
(function (scope) {
  "use strict";

  const EPSILON = 1e-8;

  function fail(message) {
    throw new Error(message);
  }

  function finiteVector(values, name) {
    if (!Array.isArray(values) || values.length === 0 || !values.every(Number.isFinite)) {
      fail(`${name} must be a non-empty finite array`);
    }
    return values.map(Number);
  }

  function stableHash(value) {
    const canonical = (item) => {
      if (Array.isArray(item)) return item.map(canonical);
      if (item && typeof item === "object") return Object.fromEntries(
        Object.keys(item).sort().map((key) => [key, canonical(item[key])])
      );
      return item;
    };
    const source = JSON.stringify(canonical(value));
    let hash = 2166136261;
    for (let i = 0; i < source.length; i += 1) {
      hash ^= source.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return `fnv1a32:${(hash >>> 0).toString(16).padStart(8, "0")}`;
  }

  function validateProblem(raw) {
    const losses = finiteVector(raw.losses, "losses");
    const payoffs = raw.payoffs;
    if (!Array.isArray(payoffs) || payoffs.length !== losses.length) {
      fail("payoffs must align with losses");
    }
    const columns = Array.isArray(payoffs[0]) ? payoffs[0].length : 0;
    if (!columns || !payoffs.every((row) => Array.isArray(row) && row.length === columns && row.every(Number.isFinite))) {
      fail("payoffs must be a finite scenario-by-candidate matrix");
    }
    if (!Array.isArray(raw.scenario_ids) || raw.scenario_ids.length !== losses.length || new Set(raw.scenario_ids).size !== losses.length) {
      fail("scenario_ids must be unique and align with losses");
    }
    if (!Array.isArray(raw.candidate_ids) || raw.candidate_ids.length !== columns || new Set(raw.candidate_ids).size !== columns) {
      fail("candidate_ids must be unique and align with payoffs");
    }
    if (raw.scenario_type === "stress" && raw.weights == null) {
      fail("stress scenarios without weights are not predictive optimization inputs");
    }
    const weights = raw.weights == null ? Array(losses.length).fill(1 / losses.length) : finiteVector(raw.weights, "weights");
    if (weights.length !== losses.length || weights.some((weight) => weight < 0) || Math.abs(weights.reduce((a, b) => a + b, 0) - 1) > EPSILON) {
      fail("weights must be aligned, non-negative, and sum to one");
    }
    const costs = raw.unit_costs == null ? Array(columns).fill(0) : finiteVector(raw.unit_costs, "unit_costs");
    if (costs.length !== columns || costs.some((cost) => cost < 0)) fail("invalid unit_costs");
    const lotSizes = raw.lot_sizes == null ? Array(columns).fill(1) : finiteVector(raw.lot_sizes, "lot_sizes");
    if (lotSizes.length !== columns || lotSizes.some((lot) => lot <= 0)) fail("invalid lot_sizes");
    const lower = raw.lower_bounds == null ? Array(columns).fill(0) : finiteVector(raw.lower_bounds, "lower_bounds");
    const upper = raw.upper_bounds == null ? Array(columns).fill(Infinity) : raw.upper_bounds.map(Number);
    if (lower.length !== columns || upper.length !== columns || upper.some((value, index) => !(Number.isFinite(value) || value === Infinity) || value < lower[index])) fail("invalid position bounds");
    if (!raw.allow_short && lower.some((value) => value < 0)) fail("short positions require allow_short");
    const reference = raw.reference_positions == null ? Array(columns).fill(0) : finiteVector(raw.reference_positions, "reference_positions");
    if (reference.length !== columns || raw.turnover_limit != null && (!(Number(raw.turnover_limit) >= 0))) fail("invalid turnover constraint");
    const stations = raw.station_ids == null ? [...raw.candidate_ids] : raw.station_ids;
    const regions = raw.region_ids == null ? [...raw.candidate_ids] : raw.region_ids;
    if (!Array.isArray(stations) || !Array.isArray(regions) || stations.length !== columns || regions.length !== columns) fail("group IDs must align to candidates");
    const fixedCost = Number(raw.fixed_cost || 0);
    if (!Number.isFinite(fixedCost) || fixedCost < 0) fail("fixed_cost must be finite and non-negative");
    for (const [name, value, maximum] of [["max_active", raw.max_active, columns], ["max_stations", raw.max_stations, new Set(stations).size]]) {
      if (value != null && (!Number.isInteger(value) || value < 1 || value > maximum)) fail(`invalid ${name}`);
    }
    for (const [name, limits, groups] of [["station", raw.station_limits || {}, stations], ["region", raw.region_limits || {}, regions]]) {
      if (typeof limits !== "object" || Object.entries(limits).some(([group, limit]) => !groups.includes(group) || !Number.isFinite(Number(limit)) || Number(limit) < 0)) fail(`invalid ${name}_limits`);
    }
    return {
      ...raw, losses, payoffs: payoffs.map((row) => row.map(Number)), weights, unit_costs: costs, lower_bounds: lower,
      upper_bounds: upper, lot_sizes: lotSizes, fixed_cost: fixedCost, currency: raw.currency || "USD", reference_positions: reference,
      turnover_limit: raw.turnover_limit == null ? null : Number(raw.turnover_limit), station_ids: stations, region_ids: regions,
      station_limits: raw.station_limits || {}, region_limits: raw.region_limits || {},
    };
  }

  function deterministicCost(problem, positions) {
    return problem.fixed_cost + positions.reduce((sum, position, index) => sum + Math.abs(position) * problem.unit_costs[index], 0);
  }

  function residualLoss(problem, positions) {
    if (!Array.isArray(positions) || positions.length !== problem.candidate_ids.length) fail("positions do not align");
    const cost = deterministicCost(problem, positions);
    return problem.losses.map((loss, scenario) => loss - problem.payoffs[scenario].reduce((sum, payoff, candidate) => sum + payoff * positions[candidate], 0) + cost);
  }

  function constraintResiduals(problem, positions) {
    const residuals = {
      lower_bounds: Math.min(...positions.map((value, i) => value - problem.lower_bounds[i])),
      upper_bounds: Math.min(...positions.map((value, i) => problem.upper_bounds[i] - value)),
    };
    const cost = deterministicCost(problem, positions);
    if (problem.cash_budget != null) residuals.cash_budget = Number(problem.cash_budget) - cost;
    if (problem.gross_limit != null) residuals.gross_limit = Number(problem.gross_limit) - positions.reduce((sum, value) => sum + Math.abs(value), 0);
    const net = positions.reduce((sum, value) => sum + value, 0);
    if (problem.net_lower != null) residuals.net_lower = net - Number(problem.net_lower);
    if (problem.net_upper != null) residuals.net_upper = Number(problem.net_upper) - net;
    if (problem.max_active != null) residuals.max_active = Number(problem.max_active) - positions.filter((value) => Math.abs(value) > EPSILON).length;
    if (problem.turnover_limit != null) residuals.turnover_limit = Number(problem.turnover_limit) - positions.reduce((sum, value, i) => sum + Math.abs(value - problem.reference_positions[i]), 0);
    for (const [station, limit] of Object.entries(problem.station_limits)) residuals[`station:${station}`] = Number(limit) - positions.reduce((sum, value, i) => sum + (problem.station_ids[i] === station ? Math.abs(value) : 0), 0);
    for (const [region, limit] of Object.entries(problem.region_limits)) residuals[`region:${region}`] = Number(limit) - positions.reduce((sum, value, i) => sum + (problem.region_ids[i] === region ? Math.abs(value) : 0), 0);
    if (problem.max_stations != null) residuals.max_stations = Number(problem.max_stations) - new Set(positions.flatMap((value, i) => Math.abs(value) > EPSILON ? [problem.station_ids[i]] : [])).size;
    return residuals;
  }

  function expectedShortfall(losses, weights, alpha = 0.90) {
    if (!(alpha > 0 && alpha < 1)) fail("alpha must be in (0, 1)");
    const values = finiteVector(losses, "losses");
    const probability = finiteVector(weights, "weights");
    return Math.min(...values.map((eta) => eta + values.reduce((sum, loss, i) => sum + probability[i] * Math.max(loss - eta, 0), 0) / (1 - alpha)));
  }

  function riskStatistics(losses, weights, alpha = 0.90) {
    const mean = losses.reduce((sum, loss, i) => sum + loss * weights[i], 0);
    const variance = losses.reduce((sum, loss, i) => sum + weights[i] * (loss - mean) ** 2, 0);
    return { mean, variance, standard_deviation: Math.sqrt(variance), expected_shortfall: expectedShortfall(losses, weights, alpha) };
  }

  function payoff(kind, index, spec) {
    const multiplier = Number(spec.multiplier ?? 1);
    const values = finiteVector(index, "index");
    if (!Number.isFinite(multiplier) || multiplier < 0) fail("invalid payoff multiplier");
    if (kind === "linear") {
      const entry = Number(spec.entry_level);
      if (!Number.isFinite(entry)) fail("linear payoff requires finite entry_level");
      return values.map((value) => multiplier * (value - entry));
    }
    if (!["call", "put", "call_spread", "put_spread", "collar"].includes(kind)) fail(`unsupported payoff kind ${kind}`);
    const strike = Number(spec.strike);
    if (!Number.isFinite(strike)) fail("option payoff requires finite strike");
    const option = (optionKind, optionStrike) => values.map((value) => multiplier * Math.max(optionKind === "put" ? optionStrike - value : value - optionStrike, 0));
    if (kind === "call_spread") {
      const high = Number(spec.high_strike); if (!Number.isFinite(high) || high <= strike) fail("call_spread requires high_strike above strike");
      return option("call", strike).map((value, i) => value - option("call", high)[i]);
    }
    if (kind === "put_spread") {
      const low = Number(spec.low_strike); if (!Number.isFinite(low) || low >= strike) fail("put_spread requires low_strike below strike");
      return option("put", strike).map((value, i) => value - option("put", low)[i]);
    }
    if (kind === "collar") {
      const callStrike = Number(spec.call_strike); if (!Number.isFinite(callStrike) || callStrike < strike) fail("collar requires call_strike at or above put strike");
      return option("put", strike).map((value, i) => value - option("call", callStrike)[i]);
    }
    const raw = option(kind, strike);
    if (spec.cap == null) return raw;
    const cap = Number(spec.cap); if (!Number.isFinite(cap) || cap < 0) fail("option cap must be finite and non-negative");
    return raw.map((value) => Math.min(value, cap));
  }

  function alignedColumn(envelope, entityId, name) {
    if (!envelope || !Array.isArray(envelope.scenario_ids) || !Array.isArray(envelope.entity_ids) || !Array.isArray(envelope.values)) fail(`${name} envelope is invalid`);
    const column = envelope.entity_ids.indexOf(entityId);
    if (column < 0 || envelope.values.length !== envelope.scenario_ids.length) fail(`${name} entity lacks scenario support`);
    return envelope.values.map((row) => Number(row[column]));
  }

  function compileHoldings({ county_scenarios, station_scenarios, holdings, problem = {} }) {
    if (county_scenarios.scenario_set_id !== station_scenarios.scenario_set_id || JSON.stringify(county_scenarios.scenario_ids) !== JSON.stringify(station_scenarios.scenario_ids)) fail("county/station scenario coordinates differ");
    const loss = Array(county_scenarios.scenario_ids.length).fill(0);
    const payoffs = []; const candidate_ids = []; const costs = [];
    holdings.forEach((holding) => {
      if (holding.candidate_id) {
        const path = alignedColumn(station_scenarios, holding.entity_id, holding.row_id || "holding");
        payoffs.push(payoff(holding.payoff_spec.kind, path, holding.payoff_spec));
        candidate_ids.push(holding.candidate_id); costs.push(Number(holding.unit_cost || 0));
      } else {
        const lossKind = holding.loss_kind || holding.kind;
        if (lossKind === "contract_payoff") {
          const structure = holding.payoff_structure;
          if (!["monthly_option", "option_on_strip", "sum_of_monthly_options"].includes(structure)) fail("contract_payoff requires a supported payoff_structure");
          const direction = Number(holding.direction);
          if (!Number.isFinite(direction)) fail("contract_payoff requires finite direction");
          const members = structure === "monthly_option" ? [holding.entity_id] : holding.member_entity_ids;
          if (!Array.isArray(members) || !members.length || members.length > 12 || new Set(members).size !== members.length) fail("contract_payoff requires 1-12 unique exact member_entity_ids");
          const memberPaths = members.map((entity) => alignedColumn(county_scenarios, entity, holding.row_id || "contract claim"));
          const claim = structure === "option_on_strip"
            ? payoff(holding.payoff_spec?.kind, memberPaths[0].map((_, scenario) => memberPaths.reduce((sum, path) => sum + path[scenario], 0)), holding.payoff_spec || {})
            : memberPaths.reduce((sum, path) => sum.map((value, scenario) => value + payoff(holding.payoff_spec?.kind, path, holding.payoff_spec || {})[scenario]), Array(loss.length).fill(0));
          claim.forEach((value, scenario) => { loss[scenario] += direction * value; });
        } else {
          const path = alignedColumn(county_scenarios, holding.entity_id, holding.row_id || "holding");
          const amount = Number(holding.amount); const budget = Number(holding.budget);
          if (!Number.isFinite(amount) || !Number.isFinite(budget)) fail("exposure requires finite amount and budget");
          if (lossKind === "heating_shortfall") path.forEach((value, i) => { loss[i] += amount * Math.max(budget - value, 0); });
        else if (lossKind === "cooling_overrun") {
          const cap = holding.claim_cap_usd ?? holding.cap ?? Infinity;
          if (!Number.isFinite(cap) && cap !== Infinity) fail("claim cap must be finite");
          path.forEach((value, i) => { loss[i] += Math.min(cap, amount * Math.max(value - budget, 0)); });
          } else fail(`unsupported exposure loss_kind ${lossKind}`);
        }
      }
    });
    return validateProblem({ ...problem, scenario_set_id: county_scenarios.scenario_set_id, scenario_ids: county_scenarios.scenario_ids, candidate_ids, losses: loss, payoffs: loss.map((_, i) => payoffs.map((column) => column[i])), unit_costs: costs });
  }

  function evaluate(raw, positions, alpha = 0.90) {
    const problem = validateProblem(raw);
    const residual = residualLoss(problem, positions);
    return {
      status: "available", scenario_set_id: problem.scenario_set_id, scenario_id_hash: stableHash(problem.scenario_ids),
      currency: problem.currency, units: "USD", positions: [...positions], deterministic_cost: deterministicCost(problem, positions),
      residual_loss: residual, risk: riskStatistics(residual, problem.weights, alpha), constraint_residuals: constraintResiduals(problem, positions), input_hash: stableHash(raw),
    };
  }

  scope.WbaPortfolio = { alignedColumn, compileHoldings, constraintResiduals, deterministicCost, evaluate, expectedShortfall, payoff, residualLoss, riskStatistics, stableHash, validateProblem };
})(self);
