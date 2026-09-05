"""Independent hand checks for V2 portfolio signs, tails, payoffs and lots."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

import numpy as np
import pytest

from weather_basis.portfolio import (
    PortfolioProblem,
    expected_shortfall,
    optimize,
    residual_loss,
    risk_statistics,
)
from weather_basis.portfolio.baselines import evaluate_baseline
from weather_basis.portfolio.payoffs import call, call_spread, put
from weather_basis.portfolio.risk import weighted_quantile

FIXTURES = Path(__file__).parents[1] / "fixtures" / "v2" / "portfolio_hand_cases.json"
portfolio_optimize = import_module("weather_basis.portfolio.optimize")


def _case(identifier: str) -> dict:
    return next(
        item for item in json.loads(FIXTURES.read_text())["cases"] if item["id"] == identifier
    )


def _problem(case: dict) -> PortfolioProblem:
    return PortfolioProblem(
        losses=np.asarray(case["exposure_loss"]),
        payoffs=np.asarray(case["long_unit_payoffs"]),
        scenario_ids=tuple(case["scenario_ids"]),
        candidate_ids=tuple(f"candidate-{i}" for i in range(len(case["long_unit_payoffs"][0]))),
        weights=np.asarray(case["weights"]),
        unit_costs=np.asarray(case.get("cost_per_unit", [0.0])),
        fixed_cost=case.get("terminal_cost", 0.0),
        lot_sizes=np.asarray(case.get("lot_sizes", [1.0])),
        upper_bounds=(None if "upper_bounds" not in case else np.asarray(case["upper_bounds"])),
    )


def test_ledger_hand_cases_apply_cost_once_and_signed_position_once() -> None:
    long_case, short_case = _case("ledger-perfect-hedge"), _case("ledger-short-sign")
    long_problem, short_problem = _problem(long_case), _problem(short_case)
    assert residual_loss(long_problem, np.asarray(long_case["positions"])) == pytest.approx(
        long_case["expected"]["residual_loss"]
    )
    assert residual_loss(short_problem, np.asarray(short_case["positions"])) == pytest.approx(
        short_case["expected"]["residual_loss"]
    )
    risk = risk_statistics(long_problem.losses, long_problem.weights)
    assert risk.mean == pytest.approx(long_case["expected"]["unhedged_mean"])
    assert risk.variance == pytest.approx(long_case["expected"]["unhedged_variance"])


def test_weighted_es_uses_fractional_tail_mass() -> None:
    case = _case("weighted-fractional-tail")
    losses, weights = np.asarray(case["losses"]), np.asarray(case["weights"])
    assert expected_shortfall(losses, weights, 0.90) == pytest.approx(case["expected"]["es_90"])
    assert expected_shortfall(losses, weights, 0.95) == pytest.approx(case["expected"]["es_95"])


def test_weighted_es_matches_ru_reference_with_irregular_tied_losses() -> None:
    losses = np.array([1.0, 4.0, 4.0, 10.0])
    weights = np.array([0.30, 0.20, 0.15, 0.35])
    alpha = 0.55
    brute = min(
        eta + np.dot(weights, np.maximum(losses - eta, 0.0)) / (1 - alpha)
        for eta in losses
    )
    assert weighted_quantile(losses, weights, alpha) == pytest.approx(4.0)
    assert expected_shortfall(losses, weights, alpha) == pytest.approx(brute)


def test_long_unit_payoff_identities() -> None:
    case = _case("payoff-identities")
    index, strike = np.asarray(case["index"]), case["strike"]
    assert call(index, strike) == pytest.approx(case["expected"]["call"])
    assert put(index, strike) == pytest.approx(case["expected"]["put"])
    assert call(index, strike) - put(index, strike) == pytest.approx(
        case["expected"]["call_minus_put"]
    )
    assert call(index, strike, cap=3) == pytest.approx(case["expected"]["capped_call_cap_3"])
    assert call_spread(index, 10, 15) == pytest.approx(case["expected"]["call_spread_10_15"])


def test_actual_lots_are_resolved_and_reevaluated() -> None:
    case = _case("integer-lot-recompute")
    result = optimize(_problem(case), "mse", lots=True)
    assert result.status == "optimal"
    assert result.continuous_positions == pytest.approx(case["expected"]["continuous_position"])
    assert result.positions == pytest.approx(case["expected"]["implemented_position"])
    assert result.residual_loss == pytest.approx(case["expected"]["implemented_residual_loss"])
    assert result.objective_value == pytest.approx(case["expected"]["implemented_mse"])


def test_infeasible_budget_is_not_reported_as_no_hedge() -> None:
    case = _case("infeasible-required-hedge-budget")
    constraints = case["constraints"]
    problem = PortfolioProblem(
        losses=np.asarray(case["exposure_loss"]),
        payoffs=np.asarray(case["long_unit_payoffs"]),
        scenario_ids=tuple(case["scenario_ids"]),
        candidate_ids=("candidate",),
        weights=np.asarray(case["weights"]),
        unit_costs=np.asarray(case["cost_per_unit"]),
        lower_bounds=np.asarray(constraints["position_lower"]),
        cash_budget=constraints["cash_budget"],
    )
    result = optimize(problem, "es")
    assert result.status == "infeasible"
    assert result.positions is None


def test_null_weight_stress_scenarios_are_rejected_for_predictive_optimization() -> None:
    with pytest.raises(ValueError, match="stress scenarios"):
        PortfolioProblem(
            losses=np.array([1.0]),
            payoffs=np.array([[1.0]]),
            scenario_ids=("stress",),
            candidate_ids=("candidate",),
            scenario_type="stress",
        )


def test_baseline_reports_infeasible_position_instead_of_presenting_it_as_executable() -> None:
    problem = PortfolioProblem(
        losses=np.array([0.0, 10.0]),
        payoffs=np.array([[0.0], [10.0]]),
        scenario_ids=("a", "b"),
        candidate_ids=("nearest",),
        weights=np.array([0.5, 0.5]),
        unit_costs=np.array([2.0]),
        cash_budget=1.0,
    )
    result = evaluate_baseline(problem, "nearest", np.array([1.0]))
    assert result.status == "infeasible"
    assert result.reason == "cash_budget"


def test_turnover_and_station_concentration_are_constraints_not_display_only() -> None:
    problem = PortfolioProblem(
        losses=np.array([0.0, 10.0]),
        payoffs=np.array([[0.0, 0.0], [10.0, 10.0]]),
        scenario_ids=("a", "b"),
        candidate_ids=("a-jan", "a-feb"),
        weights=np.array([0.5, 0.5]),
        upper_bounds=np.array([2.0, 2.0]),
        reference_positions=np.array([1.0, 0.0]),
        turnover_limit=0.25,
        station_ids=("ORD", "ORD"),
        station_limits={"ORD": 1.0},
        max_stations=1,
    )
    rejected = evaluate_baseline(problem, "over-concentrated", np.array([1.5, 0.0]))
    assert rejected.status == "infeasible"
    assert rejected.reason == "turnover_limit"
    solved = optimize(problem, "variance")
    assert solved.status in {"optimal", "feasible_suboptimal"}
    assert abs(solved.positions.sum() - 1.0) < 1e-7
    assert solved.constraint_residuals["turnover_limit"] >= -1e-7
    assert solved.constraint_residuals["station:ORD"] >= -1e-7


def test_min_cost_es_target_includes_fixed_cost_once() -> None:
    problem = PortfolioProblem(
        losses=np.array([10.0, 10.0]),
        payoffs=np.array([[10.0], [10.0]]),
        scenario_ids=("a", "b"),
        candidate_ids=("hedge",),
        upper_bounds=np.array([1.0]),
        unit_costs=np.array([1.0]),
        fixed_cost=5.0,
    )
    solved = optimize(problem, "min_cost_es", es_target=6.0)
    assert solved.status == "optimal"
    assert solved.positions == pytest.approx([1.0])
    assert solved.risk.expected_shortfall == pytest.approx(6.0)
    assert solved.deterministic_cost == pytest.approx(6.0)
    assert optimize(problem, "min_cost_es", es_target=5.0).status == "infeasible"


def test_nonbinding_cardinality_does_not_repeat_identical_solves(monkeypatch) -> None:
    problem = PortfolioProblem(
        losses=np.array([1.0, 10.0]),
        payoffs=np.array([[0.0, 0.0], [10.0, 10.0]]),
        scenario_ids=("a", "b"),
        candidate_ids=("north", "south"),
        upper_bounds=np.array([1.0, 1.0]),
        max_active=2,
        station_ids=("N", "S"),
        max_stations=2,
    )
    calls = 0
    original = portfolio_optimize._solve_active

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(portfolio_optimize, "_solve_active", counted)
    constrained = optimize(problem, "es")
    unconstrained = optimize(
        PortfolioProblem(
            losses=problem.losses,
            payoffs=problem.payoffs,
            scenario_ids=problem.scenario_ids,
            candidate_ids=problem.candidate_ids,
            upper_bounds=problem.upper_bounds,
            station_ids=problem.station_ids,
        ),
        "es",
    )
    assert calls == 2  # One constrained solve and one reference solve.
    assert constrained.positions == pytest.approx(unconstrained.positions)
    assert constrained.objective_value == pytest.approx(unconstrained.objective_value)
