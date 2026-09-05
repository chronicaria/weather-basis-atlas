"""Transparent SciPy reference solvers for V2 finite portfolio problems."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Literal

import numpy as np
from scipy import sparse
from scipy.optimize import Bounds, LinearConstraint, OptimizeResult, linprog, milp, minimize

from .ledger import PortfolioProblem, deterministic_cost, residual_loss
from .risk import RiskStats, risk_statistics

Objective = Literal["variance", "mse", "es", "min_cost_es"]


@dataclass(frozen=True)
class OptimizationResult:
    status: Literal["optimal", "feasible_suboptimal", "infeasible", "numerical_failure"]
    objective: str
    positions: np.ndarray | None
    continuous_positions: np.ndarray | None
    residual_loss: np.ndarray | None
    deterministic_cost: float | None
    risk: RiskStats | None
    objective_value: float | None
    constraint_residuals: dict[str, float]
    binding_constraints: tuple[str, ...]
    message: str


def _bounds(problem: PortfolioProblem, active: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lower, upper = problem.lower_bounds.copy(), problem.upper_bounds.copy()
    lower[~active], upper[~active] = 0.0, 0.0
    return lower, upper


def _constraint_residuals(problem: PortfolioProblem, positions: np.ndarray) -> dict[str, float]:
    result: dict[str, float] = {
        "lower_bounds": float(np.min(positions - problem.lower_bounds)),
        "upper_bounds": float(np.min(problem.upper_bounds - positions)),
    }
    cost = deterministic_cost(problem, positions)
    if problem.cash_budget is not None:
        result["cash_budget"] = problem.cash_budget - cost
    if problem.gross_limit is not None:
        result["gross_limit"] = problem.gross_limit - float(np.abs(positions).sum())
    total = float(positions.sum())
    if problem.net_lower is not None:
        result["net_lower"] = total - problem.net_lower
    if problem.net_upper is not None:
        result["net_upper"] = problem.net_upper - total
    if problem.max_active is not None:
        result["max_active"] = float(
            problem.max_active - np.count_nonzero(np.abs(positions) > 1e-8)
        )
    if problem.turnover_limit is not None:
        result["turnover_limit"] = problem.turnover_limit - float(
            np.abs(positions - problem.reference_positions).sum()
        )
    for identifier, limit in problem.station_limits.items():
        mask = np.asarray(problem.station_ids) == identifier
        result[f"station:{identifier}"] = limit - float(np.abs(positions[mask]).sum())
    for identifier, limit in problem.region_limits.items():
        mask = np.asarray(problem.region_ids) == identifier
        result[f"region:{identifier}"] = limit - float(np.abs(positions[mask]).sum())
    if problem.max_stations is not None:
        active_stations = {
            station
            for station, position in zip(problem.station_ids, positions, strict=True)
            if abs(position) > 1e-8
        }
        result["max_stations"] = float(problem.max_stations - len(active_stations))
    return result


def _result(
    problem: PortfolioProblem,
    objective: Objective,
    positions: np.ndarray | None,
    continuous: np.ndarray | None,
    status: Literal["optimal", "feasible_suboptimal", "infeasible", "numerical_failure"],
    message: str,
    alpha: float,
) -> OptimizationResult:
    if positions is None:
        return OptimizationResult(
            status, objective, None, continuous, None, None, None, None, {}, (), message
        )
    residual = residual_loss(problem, positions)
    risk = risk_statistics(residual, problem.weights, alpha=alpha)
    value = {
        "variance": risk.variance,
        "mse": float(np.dot(problem.weights, residual**2)),
        "es": risk.expected_shortfall,
    }.get(objective)
    if objective == "min_cost_es":
        value = deterministic_cost(problem, positions)
    residuals = _constraint_residuals(problem, positions)
    bindings = tuple(name for name, value_ in residuals.items() if abs(value_) <= 1e-7)
    return OptimizationResult(
        status,
        objective,
        positions,
        continuous,
        residual,
        deterministic_cost(problem, positions),
        risk,
        value,
        residuals,
        bindings,
        message,
    )


def _linear_constraints(problem: PortfolioProblem) -> tuple[np.ndarray, np.ndarray]:
    """SLSQP inequality rows A h >= b; absolute-value constraints are handled separately."""
    rows: list[np.ndarray] = []
    values: list[float] = []
    j = problem.payoffs.shape[1]
    if problem.net_lower is not None:
        rows.append(np.ones(j))
        values.append(problem.net_lower)
    if problem.net_upper is not None:
        rows.append(-np.ones(j))
        values.append(-problem.net_upper)
    return np.asarray(rows), np.asarray(values)


def _continuous_qp(
    problem: PortfolioProblem, objective: Objective, alpha: float, active: np.ndarray
) -> OptimizeResult:
    lower, upper = _bounds(problem, active)
    start = np.clip(np.zeros_like(lower), lower, upper)
    rows, values = _linear_constraints(problem)
    constraints = []
    if rows.size:
        constraints.append(LinearConstraint(rows, values, np.full(values.size, np.inf)))
    if problem.cash_budget is not None:
        constraints.append(
            {
                "type": "ineq",
                "fun": lambda h: problem.cash_budget - deterministic_cost(problem, h),
            }
        )
    if problem.gross_limit is not None:
        constraints.append({"type": "ineq", "fun": lambda h: problem.gross_limit - np.abs(h).sum()})
    if problem.turnover_limit is not None:
        constraints.append(
            {
                "type": "ineq",
                "fun": lambda h: (
                    problem.turnover_limit - np.abs(h - problem.reference_positions).sum()
                ),
            }
        )
    for identifier, limit in problem.station_limits.items():
        mask = np.asarray(problem.station_ids) == identifier
        constraints.append(
            {"type": "ineq", "fun": lambda h, m=mask, cap=limit: cap - np.abs(h[m]).sum()}
        )
    for identifier, limit in problem.region_limits.items():
        mask = np.asarray(problem.region_ids) == identifier
        constraints.append(
            {"type": "ineq", "fun": lambda h, m=mask, cap=limit: cap - np.abs(h[m]).sum()}
        )

    def fn(h: np.ndarray) -> float:
        residual = residual_loss(problem, h)
        if objective == "variance":
            mean = np.dot(problem.weights, residual)
            return float(np.dot(problem.weights, (residual - mean) ** 2))
        if objective == "mse":
            return float(np.dot(problem.weights, residual**2))
        return risk_statistics(residual, problem.weights, alpha=alpha).expected_shortfall

    return minimize(
        fn,
        start,
        method="SLSQP",
        bounds=Bounds(lower, upper),
        constraints=constraints,
        options={"ftol": 1e-10, "maxiter": 1000},
    )


def _es_lp(
    problem: PortfolioProblem,
    alpha: float,
    active: np.ndarray,
    *,
    min_cost_target: float | None = None,
    integer: bool = False,
):
    """Build linear ES problem with h, |h|, eta and scenario-tail slack variables."""
    s, j = problem.payoffs.shape
    lower, upper = _bounds(problem, active)
    lots = problem.lot_sizes if integer else np.ones(j)
    # h variables are lot counts when integer=True; a remains absolute physical position.
    n = 3 * j + 1 + s
    h_slice = slice(0, j)
    a_slice = slice(j, 2 * j)
    turnover_slice = slice(2 * j, 3 * j)
    eta = 3 * j
    slack = slice(3 * j + 1, n)
    c = np.zeros(n)
    if min_cost_target is None:
        c[eta] = 1.0
        c[slack] = problem.weights / (1 - alpha)
    else:
        c[a_slice] = problem.unit_costs
    row_indices: list[int] = []
    column_indices: list[int] = []
    values: list[float] = []
    rhs: list[float] = []
    row_number = 0

    def add_row(entries: list[tuple[int, float]], bound: float) -> None:
        nonlocal row_number
        for column, value in entries:
            if value:
                row_indices.append(row_number)
                column_indices.append(column)
                values.append(float(value))
        rhs.append(float(bound))
        row_number += 1

    # residual - eta - slack <= 0
    for scenario, (row, loss) in enumerate(zip(problem.payoffs, problem.losses, strict=True)):
        add_row(
            [(k, -row[k] * lots[k]) for k in range(j)]
            + [(j + k, problem.unit_costs[k]) for k in range(j)]
            + [(eta, -1), (slack.start + scenario, -1)],
            -loss - problem.fixed_cost,
        )
    for k in range(j):
        add_row([(k, lots[k]), (j + k, -1)], 0)
        if problem.turnover_limit is not None:
            add_row(
                [(k, lots[k]), (turnover_slice.start + k, -1)],
                problem.reference_positions[k],
            )
            add_row(
                [(k, -lots[k]), (turnover_slice.start + k, -1)],
                -problem.reference_positions[k],
            )
        add_row([(k, -lots[k]), (j + k, -1)], 0)
    if problem.cash_budget is not None:
        add_row(
            [(j + k, problem.unit_costs[k]) for k in range(j)],
            problem.cash_budget - problem.fixed_cost,
        )
    if problem.gross_limit is not None:
        add_row([(j + k, 1) for k in range(j)], problem.gross_limit)
    if problem.turnover_limit is not None:
        add_row(
            [(turnover_slice.start + k, 1) for k in range(j)], problem.turnover_limit
        )
    for identifier, limit in problem.station_limits.items():
        add_row(
            [(j + k, 1) for k, station in enumerate(problem.station_ids) if station == identifier],
            limit,
        )
    for identifier, limit in problem.region_limits.items():
        add_row(
            [(j + k, 1) for k, region in enumerate(problem.region_ids) if region == identifier],
            limit,
        )
    if problem.net_upper is not None:
        add_row([(k, lots[k]) for k in range(j)], problem.net_upper)
    if problem.net_lower is not None:
        add_row([(k, -lots[k]) for k in range(j)], -problem.net_lower)
    if min_cost_target is not None:
        # ES expression with the already-declared cost: eta + tail expectation <= target.
        add_row(
            [(eta, 1)]
            + [
                (slack.start + scenario, problem.weights[scenario] / (1 - alpha))
                for scenario in range(s)
            ],
            min_cost_target,
        )
    bounds = (
        list(zip(lower / lots, upper / lots, strict=True))
        + [(0, np.inf)] * j
        + [(0, np.inf)] * j
        + [(-np.inf, np.inf)]
        + [(0, np.inf)] * s
    )
    matrix = sparse.coo_matrix(
        (values, (row_indices, column_indices)), shape=(row_number, n)
    ).tocsr()
    vector = np.asarray(rhs)
    if integer:
        integrality = np.zeros(n, dtype=int)
        integrality[h_slice] = 1
        answer = milp(
            c,
            integrality=integrality,
            bounds=Bounds(*np.asarray(bounds).T),
            constraints=LinearConstraint(matrix, -np.inf, vector),
            options={"time_limit": 10.0},
        )
    else:
        answer = linprog(c, A_ub=matrix, b_ub=vector, bounds=bounds, method="highs")
    return answer, (lambda x: x[h_slice] * lots)


def _solve_active(
    problem: PortfolioProblem,
    objective: Objective,
    alpha: float,
    active: np.ndarray,
    integer: bool,
    es_target: float | None,
):
    if objective in {"es", "min_cost_es"}:
        answer, positions = _es_lp(
            problem,
            alpha,
            active,
            min_cost_target=es_target if objective == "min_cost_es" else None,
            integer=integer,
        )
        return answer, None if answer.x is None else positions(answer.x)
    if integer:
        # Lots under a quadratic objective are a bounded enumeration refinement.
        if (
            not np.isfinite(problem.lower_bounds).all()
            or not np.isfinite(problem.upper_bounds).all()
        ):
            return OptimizeResult(
                success=False,
                message="integer QP requires finite per-contract bounds",
                x=None,
            ), None
        choices = [
            np.arange(
                np.ceil(problem.lower_bounds[k] / problem.lot_sizes[k]),
                np.floor(problem.upper_bounds[k] / problem.lot_sizes[k]) + 1,
            )
            for k in range(problem.payoffs.shape[1])
        ]
        if np.prod([len(x) for x in choices]) > 100000:
            return OptimizeResult(
                success=False, message="integer QP enumeration limit exceeded", x=None
            ), None
        best: tuple[float, np.ndarray] | None = None
        for units in np.array(np.meshgrid(*choices)).T.reshape(-1, len(choices)):
            positions = units * problem.lot_sizes
            residuals = _constraint_residuals(problem, positions)
            if min(residuals.values()) < -1e-8:
                continue
            residual = residual_loss(problem, positions)
            value = (
                float(np.dot(problem.weights, residual**2))
                if objective == "mse"
                else risk_statistics(residual, problem.weights, alpha=alpha).variance
            )
            if best is None or value < best[0]:
                best = value, positions
        return OptimizeResult(
            success=best is not None,
            message="bounded integer QP enumeration",
            x=None if best is None else best[1],
        ), None if best is None else best[1]
    answer = _continuous_qp(problem, objective, alpha, active)
    return answer, None if answer.x is None else answer.x


def optimize(
    problem: PortfolioProblem,
    objective: Objective = "es",
    *,
    alpha: float = 0.90,
    lots: bool = False,
    es_target: float | None = None,
) -> OptimizationResult:
    """Solve a finite portfolio problem and re-evaluate the actual returned positions."""
    if objective not in {"variance", "mse", "es", "min_cost_es"} or not 0 < alpha < 1:
        raise ValueError("invalid objective or tail level")
    if objective == "min_cost_es" and es_target is None:
        raise ValueError("min_cost_es requires es_target")
    j = problem.payoffs.shape[1]
    forced = np.flatnonzero(problem.lower_bounds > 1e-12)
    all_candidates = np.ones(j, dtype=bool)

    def maximal_candidate_masks() -> list[np.ndarray]:
        limit = problem.max_active
        if limit is None or limit >= j:
            return [all_candidates]
        if len(forced) > limit:
            return []
        optional = [index for index in range(j) if index not in forced]
        masks = []
        for chosen in combinations(optional, limit - len(forced)):
            mask = np.zeros(j, dtype=bool)
            mask[forced] = True
            mask[list(chosen)] = True
            masks.append(mask)
        return masks

    def maximal_station_masks() -> list[np.ndarray]:
        groups = tuple(sorted(set(problem.station_ids)))
        limit = problem.max_stations
        if limit is None or limit >= len(groups):
            return [all_candidates]
        forced_groups = {problem.station_ids[index] for index in forced}
        if len(forced_groups) > limit:
            return []
        optional = [group for group in groups if group not in forced_groups]
        masks = []
        for chosen in combinations(optional, limit - len(forced_groups)):
            allowed = forced_groups | set(chosen)
            masks.append(np.isin(problem.station_ids, tuple(allowed)))
        return masks

    # A support of maximum permitted size contains every smaller feasible support:
    # zero remains allowed for its non-forced candidates.  Deduplicate intersections
    # because candidate and station cardinality can produce the same support.
    subsets_by_key = {
        tuple((candidate & station).tolist()): candidate & station
        for candidate in maximal_candidate_masks()
        for station in maximal_station_masks()
    }
    subsets = list(subsets_by_key.values())
    best: tuple[float, np.ndarray, str] | None = None
    for active in subsets:
        answer, positions = _solve_active(problem, objective, alpha, active, lots, es_target)
        if not answer.success or positions is None:
            continue
        residuals = _constraint_residuals(problem, positions)
        if min(residuals.values()) < -1e-7:
            continue
        residual = residual_loss(problem, positions)
        value = (
            deterministic_cost(problem, positions)
            if objective == "min_cost_es"
            else (
                risk_statistics(residual, problem.weights, alpha=alpha).expected_shortfall
                if objective == "es"
                else float(np.dot(problem.weights, residual**2))
                if objective == "mse"
                else risk_statistics(residual, problem.weights, alpha=alpha).variance
            )
        )
        if best is None or value < best[0]:
            best = value, positions, str(answer.message)
    if best is None:
        return _result(
            problem,
            objective,
            None,
            None,
            "infeasible",
            "No feasible solution under declared constraints",
            alpha,
        )
    status: Literal["optimal", "feasible_suboptimal"] = "optimal"
    continuous = None
    if lots:
        base = optimize(problem, objective, alpha=alpha, lots=False, es_target=es_target)
        continuous = base.positions
    return _result(problem, objective, best[1], continuous, status, best[2], alpha)
