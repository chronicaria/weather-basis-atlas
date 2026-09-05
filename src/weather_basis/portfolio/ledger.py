"""Aligned-scenario loss ledger.  Positive loss is adverse; long payoff is beneficial."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _vector(values: np.ndarray | tuple[float, ...], name: str) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64).reshape(-1)
    if result.size == 0 or not np.isfinite(result).all():
        raise ValueError(f"{name} must be a non-empty finite vector")
    return result


@dataclass(frozen=True)
class PortfolioProblem:
    """A finite, already-aligned numerical problem compiled from canonical records."""

    losses: np.ndarray
    payoffs: np.ndarray
    scenario_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    weights: np.ndarray | None = None
    unit_costs: np.ndarray | None = None
    fixed_cost: float = 0.0
    lower_bounds: np.ndarray | None = None
    upper_bounds: np.ndarray | None = None
    lot_sizes: np.ndarray | None = None
    cash_budget: float | None = None
    gross_limit: float | None = None
    net_lower: float | None = None
    net_upper: float | None = None
    allow_short: bool = False
    max_active: int | None = None
    reference_positions: np.ndarray | None = None
    turnover_limit: float | None = None
    station_ids: tuple[str, ...] | None = None
    region_ids: tuple[str, ...] | None = None
    station_limits: dict[str, float] | None = None
    region_limits: dict[str, float] | None = None
    max_stations: int | None = None
    scenario_type: str = "physical_predictive"

    def __post_init__(self) -> None:
        losses = _vector(self.losses, "losses")
        payoffs = np.asarray(self.payoffs, dtype=np.float64)
        if payoffs.ndim != 2 or payoffs.shape[0] != losses.size or not np.isfinite(payoffs).all():
            raise ValueError("payoffs must be a finite [scenario, candidate] matrix")
        if payoffs.shape[1] == 0:
            raise ValueError("at least one candidate is required")
        if len(self.scenario_ids) != losses.size or len(set(self.scenario_ids)) != losses.size:
            raise ValueError("scenario_ids must be unique and aligned to losses")
        if (
            len(self.candidate_ids) != payoffs.shape[1]
            or len(set(self.candidate_ids)) != payoffs.shape[1]
        ):
            raise ValueError("candidate_ids must be unique and aligned to payoffs")
        if self.weights is None:
            if self.scenario_type == "stress":
                raise ValueError(
                    "stress scenarios with null weights cannot enter predictive optimization"
                )
            weights = np.full(losses.size, 1.0 / losses.size)
        else:
            weights = _vector(self.weights, "weights")
            if (
                weights.size != losses.size
                or np.any(weights < 0)
                or not np.isclose(weights.sum(), 1.0)
            ):
                raise ValueError("weights must be non-negative, aligned, and sum to one")
        columns = payoffs.shape[1]
        costs = (
            np.zeros(columns) if self.unit_costs is None else _vector(self.unit_costs, "unit_costs")
        )
        if costs.size != columns or np.any(costs < 0):
            raise ValueError("unit_costs must be non-negative and aligned")
        if not np.isfinite(self.fixed_cost) or self.fixed_cost < 0:
            raise ValueError("fixed_cost must be a non-negative finite amount")
        lower = (
            np.zeros(columns)
            if self.lower_bounds is None
            else _vector(self.lower_bounds, "lower_bounds")
        )
        upper = (
            np.full(columns, np.inf)
            if self.upper_bounds is None
            else _vector(self.upper_bounds, "upper_bounds")
        )
        if lower.size != columns or upper.size != columns or np.any(lower > upper):
            raise ValueError("invalid position bounds")
        if not self.allow_short and np.any(lower < 0):
            raise ValueError("short positions require allow_short")
        lots = np.ones(columns) if self.lot_sizes is None else _vector(self.lot_sizes, "lot_sizes")
        if lots.size != columns or np.any(lots <= 0):
            raise ValueError("lot_sizes must be positive and aligned")
        if self.cash_budget is not None and self.cash_budget < 0:
            raise ValueError("cash_budget must be non-negative")
        if self.gross_limit is not None and self.gross_limit < 0:
            raise ValueError("gross_limit must be non-negative")
        if self.max_active is not None and not 0 < self.max_active <= columns:
            raise ValueError("max_active must be between one and candidate count")
        reference = (
            np.zeros(columns)
            if self.reference_positions is None
            else _vector(self.reference_positions, "reference_positions")
        )
        if reference.size != columns:
            raise ValueError("reference_positions must align to candidates")
        if self.turnover_limit is not None and self.turnover_limit < 0:
            raise ValueError("turnover_limit must be non-negative")
        stations = self.candidate_ids if self.station_ids is None else self.station_ids
        regions = self.candidate_ids if self.region_ids is None else self.region_ids
        if len(stations) != columns or len(regions) != columns:
            raise ValueError("station_ids and region_ids must align to candidates")
        for limits, identifiers, name in (
            (self.station_limits, stations, "station"),
            (self.region_limits, regions, "region"),
        ):
            if limits is not None:
                if set(limits) - set(identifiers) or any(value < 0 for value in limits.values()):
                    raise ValueError(f"invalid {name} concentration limits")
        if self.max_stations is not None and not 0 < self.max_stations <= len(set(stations)):
            raise ValueError("max_stations must be within station universe")
        if (
            self.net_lower is not None
            and self.net_upper is not None
            and self.net_lower > self.net_upper
        ):
            raise ValueError("net bounds are reversed")
        object.__setattr__(self, "losses", losses)
        object.__setattr__(self, "payoffs", payoffs)
        object.__setattr__(self, "weights", weights)
        object.__setattr__(self, "unit_costs", costs)
        object.__setattr__(self, "lower_bounds", lower)
        object.__setattr__(self, "upper_bounds", upper)
        object.__setattr__(self, "lot_sizes", lots)
        object.__setattr__(self, "reference_positions", reference)
        object.__setattr__(self, "station_ids", tuple(stations))
        object.__setattr__(self, "region_ids", tuple(regions))
        object.__setattr__(self, "station_limits", self.station_limits or {})
        object.__setattr__(self, "region_limits", self.region_limits or {})

    @classmethod
    def from_matrices(
        cls,
        loss_matrix,
        payoff_matrix,
        *,
        weights: np.ndarray | None = None,
        unit_costs: np.ndarray | None = None,
        **kwargs,
    ) -> PortfolioProblem:
        """Compile strict aligned matrices without accepting same-shaped impostors."""
        loss_matrix.assert_same_scenarios(payoff_matrix)
        if len(loss_matrix.entity_ids) != 1:
            raise ValueError("loss matrix must contain one already-aggregated exposure-loss column")
        return cls(
            losses=loss_matrix.values[:, 0],
            payoffs=payoff_matrix.values,
            scenario_ids=loss_matrix.scenario_ids,
            candidate_ids=payoff_matrix.entity_ids,
            weights=weights,
            unit_costs=unit_costs,
            **kwargs,
        )


def deterministic_cost(problem: PortfolioProblem, positions: np.ndarray) -> float:
    positions = _vector(positions, "positions")
    if positions.size != problem.payoffs.shape[1]:
        raise ValueError("positions must align to candidates")
    return float(problem.fixed_cost + np.dot(problem.unit_costs, np.abs(positions)))


def residual_loss(problem: PortfolioProblem, positions: np.ndarray) -> np.ndarray:
    """Return ``L - G h + C(h)`` with the deterministic cost included once."""
    positions = _vector(positions, "positions")
    if positions.size != problem.payoffs.shape[1]:
        raise ValueError("positions must align to candidates")
    return problem.losses - problem.payoffs @ positions + deterministic_cost(problem, positions)
