"""Common-support portfolio baselines; callers supply declared nearest/simple positions."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .ledger import PortfolioProblem, deterministic_cost, residual_loss
from .risk import RiskStats, risk_statistics


@dataclass(frozen=True)
class BaselineResult:
    name: str
    status: str
    positions: np.ndarray | None
    residual_loss: np.ndarray | None
    deterministic_cost: float | None
    risk: RiskStats | None
    reason: str | None = None


def evaluate_baseline(
    problem: PortfolioProblem,
    name: str,
    positions: np.ndarray | None = None,
    *,
    alpha: float = 0.90,
) -> BaselineResult:
    """Evaluate a declared baseline under the exact portfolio constraints and paths."""
    positions = (
        np.zeros(problem.payoffs.shape[1])
        if positions is None
        else np.asarray(positions, dtype=float)
    )
    if positions.shape != (problem.payoffs.shape[1],) or not np.isfinite(positions).all():
        return BaselineResult(name, "infeasible", None, None, None, None, "invalid_positions")
    cost = deterministic_cost(problem, positions)
    if np.any(positions < problem.lower_bounds) or np.any(positions > problem.upper_bounds):
        return BaselineResult(name, "infeasible", None, None, cost, None, "position_bounds")
    if problem.cash_budget is not None and cost > problem.cash_budget + 1e-8:
        return BaselineResult(name, "infeasible", None, None, cost, None, "cash_budget")
    if problem.gross_limit is not None and np.abs(positions).sum() > problem.gross_limit + 1e-8:
        return BaselineResult(name, "infeasible", None, None, cost, None, "gross_limit")
    if problem.net_lower is not None and positions.sum() < problem.net_lower - 1e-8:
        return BaselineResult(name, "infeasible", None, None, cost, None, "net_lower")
    if problem.net_upper is not None and positions.sum() > problem.net_upper + 1e-8:
        return BaselineResult(name, "infeasible", None, None, cost, None, "net_upper")
    if (
        problem.max_active is not None
        and np.count_nonzero(np.abs(positions) > 1e-8) > problem.max_active
    ):
        return BaselineResult(name, "infeasible", None, None, cost, None, "max_active")
    if (
        problem.turnover_limit is not None
        and np.abs(positions - problem.reference_positions).sum() > problem.turnover_limit + 1e-8
    ):
        return BaselineResult(name, "infeasible", None, None, cost, None, "turnover_limit")
    for identifier, limit in problem.station_limits.items():
        used = np.abs(positions[np.asarray(problem.station_ids) == identifier]).sum()
        if used > limit + 1e-8:
            return BaselineResult(
                name, "infeasible", None, None, cost, None, f"station:{identifier}"
            )
    for identifier, limit in problem.region_limits.items():
        used = np.abs(positions[np.asarray(problem.region_ids) == identifier]).sum()
        if used > limit + 1e-8:
            return BaselineResult(
                name, "infeasible", None, None, cost, None, f"region:{identifier}"
            )
    residual = residual_loss(problem, positions)
    return BaselineResult(
        name,
        "feasible",
        positions,
        residual,
        cost,
        risk_statistics(residual, problem.weights, alpha=alpha),
    )
