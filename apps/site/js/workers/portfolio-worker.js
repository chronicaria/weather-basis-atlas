/* global importScripts, postMessage, self */
"use strict";

importScripts("../kernels/portfolio.js");

const SCHEMA_VERSION = "2.0";
const LIMITS = { locations: 6, exposures: 24, candidates: 39, scenarios: 2000 };
let highsPromise = null;
let cancelled = new Set();
let initialized = false;

function response(type, request, payload) {
  postMessage({ type, request_id: request.request_id, input_hash: request.input_hash, schema_version: SCHEMA_VERSION, payload });
}

function fail(request, error) {
  response("error", request, { status: "numerical_failure", reason_code: "worker_error", message: String(error.message || error) });
}

function assertRequest(request) {
  if (!request || request.schema_version !== SCHEMA_VERSION || typeof request.request_id !== "string" || typeof request.input_hash !== "string") {
    throw new Error("request requires schema_version 2.0, request_id, and input_hash");
  }
}

function assertLimits(problem) {
  const locations = new Set(problem.location_ids || []);
  const exposures = problem.exposure_rows || 1;
  if (locations.size > LIMITS.locations || exposures > LIMITS.exposures || problem.candidate_ids.length > LIMITS.candidates || problem.scenario_ids.length > LIMITS.scenarios) {
    throw new Error("browser_limit_exceeded: use the offline 10,000-path workflow");
  }
}

async function highs() {
  if (!highsPromise) {
    importScripts("../../vendor/highs/highs-1.15.2.js");
    highsPromise = self.Module({ locateFile: () => "../../vendor/highs/highs-1.15.2.wasm" });
  }
  return highsPromise;
}

function number(value) {
  return Number(value).toPrecision(17);
}

function esLp(problem, alpha, minCostTarget, lots) {
  if (problem.allow_short) throw new Error("pinned browser LP currently supports declared long-only candidates");
  const variables = problem.candidate_ids.map((_, i) => `h${i}`);
  const lotSizes = lots ? problem.lot_sizes : problem.candidate_ids.map(() => 1);
  const absolute = problem.candidate_ids.map((_, i) => `a${i}`);
  const turnover = problem.candidate_ids.map((_, i) => `t${i}`);
  const active = problem.candidate_ids.map((_, i) => `y${i}`);
  const stationGroups = [...new Set(problem.station_ids)];
  const stationActive = stationGroups.map((_, i) => `z${i}`);
  const slacks = problem.scenario_ids.map((_, i) => `u${i}`);
  const terms = (values, names) => values.map((value, i) => `${number(value)} ${names[i]}`).join(" + ");
  const target = minCostTarget == null
    ? `eta + ${terms(problem.weights.map((weight) => weight / (1 - alpha)), slacks)}`
    : terms(problem.unit_costs, absolute);
  const lines = ["Minimize", ` obj: ${target}`, "Subject To"];
  problem.losses.forEach((loss, scenario) => {
    const hedge = problem.payoffs[scenario].map((value, i) => -value * lotSizes[i]);
    const costs = problem.unit_costs;
    lines.push(` tail_${scenario}: ${terms(hedge, variables)} + ${terms(costs, absolute)} - eta - u${scenario} <= ${number(-loss - problem.fixed_cost)}`);
  });
  variables.forEach((variable, i) => lines.push(` abs_${i}: ${number(lotSizes[i])} ${variable} - a${i} <= 0`));
  if (problem.cash_budget != null) lines.push(` budget: ${terms(problem.unit_costs, absolute)} <= ${number(problem.cash_budget - problem.fixed_cost)}`);
  if (problem.gross_limit != null) lines.push(` gross: ${absolute.join(" + ")} <= ${number(problem.gross_limit)}`);
  if (problem.turnover_limit != null) {
    problem.reference_positions.forEach((reference, i) => {
      lines.push(` turnover_pos_${i}: ${number(lotSizes[i])} h${i} - t${i} <= ${number(reference)}`);
      lines.push(` turnover_neg_${i}: - ${number(lotSizes[i])} h${i} - t${i} <= ${number(-reference)}`);
    });
    lines.push(` turnover_limit: ${turnover.join(" + ")} <= ${number(problem.turnover_limit)}`);
  }
  for (const [station, limit] of Object.entries(problem.station_limits || {})) {
    lines.push(` station_${station}: ${absolute.filter((_, i) => problem.station_ids[i] === station).join(" + ")} <= ${number(limit)}`);
  }
  for (const [region, limit] of Object.entries(problem.region_limits || {})) {
    lines.push(` region_${region}: ${absolute.filter((_, i) => problem.region_ids[i] === region).join(" + ")} <= ${number(limit)}`);
  }
  if (problem.net_upper != null) lines.push(` net_upper: ${terms(lotSizes, variables)} <= ${number(problem.net_upper)}`);
  if (problem.net_lower != null) lines.push(` net_lower: - ${terms(lotSizes, variables)} <= ${number(-problem.net_lower)}`);
  if (minCostTarget != null) lines.push(` es_target: eta + ${terms(problem.weights.map((weight) => weight / (1 - alpha)), slacks)} <= ${number(minCostTarget)}`);
  if (problem.max_active != null || problem.max_stations != null) {
    if (problem.upper_bounds.some((upper) => !Number.isFinite(upper))) throw new Error("cardinality constraints require finite upper_bounds in browser solver");
    variables.forEach((variable, i) => lines.push(` active_bound_${i}: ${number(lotSizes[i])} ${variable} - ${number(problem.upper_bounds[i])} ${active[i]} <= 0`));
    if (problem.max_active != null) lines.push(` max_active: ${active.join(" + ")} <= ${number(problem.max_active)}`);
    if (problem.max_stations != null) {
      variables.forEach((_, i) => lines.push(` station_link_${i}: ${active[i]} - ${stationActive[stationGroups.indexOf(problem.station_ids[i])]} <= 0`));
      lines.push(` max_stations: ${stationActive.join(" + ")} <= ${number(problem.max_stations)}`);
    }
  }
  lines.push("Bounds");
  variables.forEach((variable, i) => {
    const upper = problem.upper_bounds[i];
    lines.push(`${number(problem.lower_bounds[i] / lotSizes[i])} <= ${variable}${Number.isFinite(upper) ? ` <= ${number(upper / lotSizes[i])}` : ""}`);
  });
  absolute.forEach((variable) => lines.push(`${variable} >= 0`));
  if (problem.turnover_limit != null) turnover.forEach((variable) => lines.push(`${variable} >= 0`));
  slacks.forEach((variable) => lines.push(`${variable} >= 0`));
  lines.push("eta free");
  if (lots) lines.push("Generals", ` ${variables.join(" ")}`);
  if (problem.max_active != null || problem.max_stations != null) lines.push("Binaries", ` ${active.concat(problem.max_stations != null ? stationActive : []).join(" ")}`);
  lines.push("End");
  return lines.join("\n");
}

function qpModel(problem, objective) {
  const names = problem.candidate_ids.map((_, i) => `h${i}`);
  const turnover = problem.candidate_ids.map((_, i) => `t${i}`);
  const terms = (values, variables) => values.map((value, i) => `${number(value)} ${variables[i]}`).join(" + ");
  const rows = problem.losses.map((loss, s) => ({
    loss: objective === "mse" ? loss + problem.fixed_cost : loss,
    hedge: problem.payoffs[s].map((value, j) => objective === "mse" ? value - problem.unit_costs[j] : value),
  }));
  const mean = (values) => values.reduce((sum, value, i) => sum + value * problem.weights[i], 0);
  const centered = objective === "variance" ? rows.map((row) => ({ loss: row.loss - mean(problem.losses), hedge: row.hedge.map((value, j) => value - mean(problem.payoffs.map((payoff) => payoff[j]))) })) : rows;
  const linear = names.map((_, j) => -2 * centered.reduce((sum, row, s) => sum + problem.weights[s] * row.loss * row.hedge[j], 0));
  const quadratic = [];
  for (let i = 0; i < names.length; i += 1) {
    for (let j = i; j < names.length; j += 1) {
      const hessian = centered.reduce(
        (sum, row, s) => sum + problem.weights[s] * row.hedge[i] * row.hedge[j], 0
      );
      const coefficient = i === j ? 2 * hessian : 4 * hessian;
      if (Math.abs(coefficient) > 1e-14) {
        quadratic.push(i === j ? `${number(coefficient)} ${names[i]} ^ 2` : `${number(coefficient)} ${names[i]} * ${names[j]}`);
      }
    }
  }
  const lines = ["Minimize", ` obj: ${linear.map((value, i) => `${number(value)} ${names[i]}`).join(" + ")} + [ ${quadratic.join(" + ")} ] / 2`, "Subject To"];
  if (problem.cash_budget != null) {
    lines.push(` budget: ${terms(problem.unit_costs, names)} <= ${number(problem.cash_budget - problem.fixed_cost)}`);
  }
  if (problem.gross_limit != null) lines.push(` gross: ${names.join(" + ")} <= ${number(problem.gross_limit)}`);
  if (problem.turnover_limit != null) {
    problem.reference_positions.forEach((reference, i) => {
      lines.push(` turnover_pos_${i}: h${i} - t${i} <= ${number(reference)}`);
      lines.push(` turnover_neg_${i}: - h${i} - t${i} <= ${number(-reference)}`);
    });
    lines.push(` turnover_limit: ${turnover.join(" + ")} <= ${number(problem.turnover_limit)}`);
  }
  for (const [station, limit] of Object.entries(problem.station_limits || {})) lines.push(` station_${station}: ${names.filter((_, i) => problem.station_ids[i] === station).join(" + ")} <= ${number(limit)}`);
  for (const [region, limit] of Object.entries(problem.region_limits || {})) lines.push(` region_${region}: ${names.filter((_, i) => problem.region_ids[i] === region).join(" + ")} <= ${number(limit)}`);
  lines.push("Bounds");
  names.forEach((name, i) => lines.push(`${number(problem.lower_bounds[i])} <= ${name}${Number.isFinite(problem.upper_bounds[i]) ? ` <= ${number(problem.upper_bounds[i])}` : ""}`));
  if (problem.turnover_limit != null) turnover.forEach((name) => lines.push(`${name} >= 0`));
  lines.push("End");
  return lines.join("\n");
}

async function optimize(request) {
  const payload = request.payload || {};
  const problem = self.WbaPortfolio.validateProblem(payload.problem);
  assertLimits(problem);
  if (request.input_hash !== self.WbaPortfolio.stableHash(payload.problem)) throw new Error("input_hash does not match problem");
  const alpha = Number(payload.alpha ?? 0.90);
  const objective = payload.objective || "es";
  if (objective === "min_cost_es" && !Number.isFinite(Number(payload.es_target))) throw new Error("min_cost_es requires finite es_target");
  if (["variance", "mse"].includes(objective) && (problem.max_active != null || problem.max_stations != null)) {
    throw new Error("unsupported_cardinality_qp: use ES/min-cost ES or the offline solver");
  }
  const started = performance.now();
  const solver = await highs();
  const model = ["es", "min_cost_es"].includes(objective)
    ? esLp(problem, alpha, objective === "min_cost_es" ? Number(payload.es_target) : null, Boolean(payload.lots))
    : ["variance", "mse"].includes(objective)
      ? qpModel(problem, objective)
      : (() => { throw new Error("unknown_objective"); })();
  const solved = solver.solve(model, { output_flag: false, time_limit: 10 });
  if (cancelled.has(request.request_id)) return null;
  const positions = problem.candidate_ids.map((_, i) => Number(solved.Columns?.[`h${i}`]?.Primal) * (payload.lots ? problem.lot_sizes[i] : 1));
  if (solved.Status !== "Optimal" || positions.some((position) => !Number.isFinite(position))) {
    return { status: solved.Status === "Infeasible" ? "infeasible" : "numerical_failure", reason_code: "solver_status", message: solved.Status, objective, scenario_set_id: problem.scenario_set_id, scenario_id_hash: self.WbaPortfolio.stableHash(problem.scenario_ids), currency: problem.currency, units: "USD" };
  }
  const evaluated = self.WbaPortfolio.evaluate(problem, positions, alpha);
  const worst = Math.min(...Object.values(evaluated.constraint_residuals));
  if (worst < -1e-7) {
    return { ...evaluated, input_hash: request.input_hash, status: "numerical_failure", objective, solver: "highs-js-1.15.2", elapsed_ms: performance.now() - started, feasibility: { max_constraint_violation: -worst }, reason_code: "constraint_violation" };
  }
  return { ...evaluated, input_hash: request.input_hash, status: "optimal", objective, solver: "highs-js-1.15.2", elapsed_ms: performance.now() - started, feasibility: { max_constraint_violation: 0 }, reason_code: null };
}

self.onmessage = async ({ data: request }) => {
  try {
    assertRequest(request);
    if (request.type === "cancel") {
      cancelled.add(request.payload?.cancel_request_id || request.request_id);
      response("cancelled", request, { status: "cancelled" });
      return;
    }
    if (request.type === "dispose") {
      highsPromise = null;
      initialized = false;
      response("result", request, { status: "disposed" });
      return;
    }
    if (request.type === "initialize") {
      await highs();
      initialized = true;
      response("ready", request, { status: "ready", limits: LIMITS, solver: "highs-js-1.15.2" });
      return;
    }
    if (!initialized) throw new Error("worker must be initialized before calculation");
    if (request.type === "evaluate") {
      const problem = self.WbaPortfolio.validateProblem(request.payload?.problem);
      assertLimits(problem);
      if (request.input_hash !== self.WbaPortfolio.stableHash(request.payload.problem)) throw new Error("input_hash does not match problem");
      response("result", request, { ...self.WbaPortfolio.evaluate(problem, request.payload.positions, request.payload.alpha), input_hash: request.input_hash });
      return;
    }
    if (request.type === "optimize") {
      const payload = await optimize(request);
      if (payload == null || cancelled.has(request.request_id)) {
        cancelled.delete(request.request_id);
        response("cancelled", request, { status: "cancelled" });
      } else response("result", request, payload);
      return;
    }
    throw new Error("unknown worker request type");
  } catch (error) {
    fail(request || { request_id: "invalid", input_hash: "invalid" }, error);
  }
};
