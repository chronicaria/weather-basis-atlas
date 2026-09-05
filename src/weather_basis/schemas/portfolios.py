"""Strict public records for a finite V2 portfolio calculation."""

from __future__ import annotations

from dataclasses import dataclass

from .base import StrictRecord, require


@dataclass(frozen=True, kw_only=True)
class PortfolioConstraints(StrictRecord):
    cash_budget: float | None = None
    gross_limit: float | None = None
    net_lower: float | None = None
    net_upper: float | None = None
    max_active: int | None = None
    allow_short: bool = False
    turnover_limit: float | None = None
    max_stations: int | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        for value in (self.cash_budget, self.gross_limit):
            require(value is None or value >= 0, "budget and gross_limit must be non-negative")
        require(self.max_active is None or self.max_active > 0, "max_active must be positive")
        require(self.max_stations is None or self.max_stations > 0, "max_stations must be positive")
        require(
            self.turnover_limit is None or self.turnover_limit >= 0,
            "turnover_limit must be non-negative",
        )
        require(
            self.net_lower is None or self.net_upper is None or self.net_lower <= self.net_upper,
            "net bounds are reversed",
        )


@dataclass(frozen=True, kw_only=True)
class PortfolioSpec(StrictRecord):
    portfolio_id: str
    scenario_set_id: str
    currency: str = "USD"
    objective: str = "es"
    tail_level: float = 0.90
    candidate_ids: tuple[str, ...] = ()
    exposure_row_ids: tuple[str, ...] = ()
    position_ids: tuple[str, ...] = ()
    contract_window_ids: tuple[str, ...] = ()
    cost_profile_id: str | None = None
    reference_book_id: str | None = None
    constraints: PortfolioConstraints = PortfolioConstraints()

    def __post_init__(self) -> None:
        super().__post_init__()
        require(
            self.portfolio_id and self.scenario_set_id, "portfolio and scenario IDs are required"
        )
        require(self.currency == "USD", "Core supports USD only")
        require(self.objective in {"variance", "mse", "es", "min_cost_es"}, "Unknown objective")
        require(0 < self.tail_level < 1, "tail_level must be in (0, 1)")
        require(len(set(self.candidate_ids)) == len(self.candidate_ids), "Duplicate candidate IDs")
        for values, label in (
            (self.exposure_row_ids, "exposure row"),
            (self.position_ids, "position"),
            (self.contract_window_ids, "contract window"),
        ):
            require(len(set(values)) == len(values), f"Duplicate {label} IDs")
