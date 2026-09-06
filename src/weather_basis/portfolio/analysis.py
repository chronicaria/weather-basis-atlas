"""Common-scenario portfolio attribution, frontiers, and reoptimized claim capital."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from .ledger import PortfolioProblem, residual_loss
from .optimize import Objective, OptimizationResult, optimize
from .risk import expected_shortfall


@dataclass(frozen=True)
class RiskDecomposition:
    unhedged_es: float
    hedged_pre_cost_es: float
    post_cost_es: float
    hedge_benefit: float
    cost_effect: float


def risk_decomposition(
    problem: PortfolioProblem, positions: np.ndarray, *, alpha: float = 0.90
) -> RiskDecomposition:
    unhedged = expected_shortfall(problem.losses, problem.weights, alpha)
    pre_cost = problem.losses - problem.payoffs @ np.asarray(positions, dtype=np.float64)
    hedged = expected_shortfall(pre_cost, problem.weights, alpha)
    post_cost = expected_shortfall(residual_loss(problem, positions), problem.weights, alpha)
    return RiskDecomposition(unhedged, hedged, post_cost, unhedged - hedged, post_cost - hedged)


def frontier(
    problem: PortfolioProblem,
    budgets: tuple[float, ...],
    objective: Objective = "es",
    *,
    alpha: float = 0.90,
    lots: bool = False,
) -> tuple[OptimizationResult, ...]:
    if tuple(sorted(set(budgets))) != budgets or any(budget < 0 for budget in budgets):
        raise ValueError("frontier budgets must be unique, ascending, and non-negative")
    return tuple(
        optimize(replace(problem, cash_budget=budget), objective, alpha=alpha, lots=lots)
        for budget in budgets
    )


@dataclass(frozen=True)
class IncrementalCapital:
    book: OptimizationResult
    book_plus_claim: OptimizationResult
    incremental_es: float | None
    incremental_cost: float | None


def incremental_capital(
    book: PortfolioProblem,
    claim_losses: np.ndarray,
    objective: Objective = "es",
    *,
    alpha: float = 0.90,
    lots: bool = False,
) -> IncrementalCapital:
    claim = np.asarray(claim_losses, dtype=np.float64).reshape(-1)
    if claim.shape != book.losses.shape or not np.isfinite(claim).all():
        raise ValueError("claim_losses must be finite and align to book scenarios")
    base = optimize(book, objective, alpha=alpha, lots=lots)
    combined = optimize(
        replace(book, losses=book.losses + claim), objective, alpha=alpha, lots=lots
    )
    if base.risk is None or combined.risk is None:
        return IncrementalCapital(base, combined, None, None)
    return IncrementalCapital(
        base,
        combined,
        combined.risk.expected_shortfall - base.risk.expected_shortfall,
        (combined.deterministic_cost or 0.0) - (base.deterministic_cost or 0.0),
    )
