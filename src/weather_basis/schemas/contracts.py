"""Strict V2 contract, listing, market, and window records."""

from __future__ import annotations

from dataclasses import dataclass

from .base import StrictRecord, require


@dataclass(frozen=True, kw_only=True)
class ContractSpec(StrictRecord):
    contract_spec_id: str
    index_definition_id: str
    station_id: str
    station_name: str
    city: str
    index: str
    product_code: str
    multiplier_usd: float
    currency: str
    tick_usd: float | None
    lot_size: int | None
    observation_rule: str
    expiry_rule: str
    settlement_rule: str
    correction_rule: str
    effective_from: str | None
    effective_to: str | None
    evidence_tier: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        require(self.index in {"HDD", "CDD"}, "index must be HDD or CDD")
        require(self.multiplier_usd > 0, "multiplier_usd must be positive")
        require(self.currency == "USD", "V2 core currency must be USD")
        require(bool(self.evidence_ids), "ContractSpec requires retained evidence")


@dataclass(frozen=True, kw_only=True)
class InstrumentListing(StrictRecord):
    instrument_listing_id: str
    contract_spec_id: str
    contract_year: int
    contract_window_id: str
    symbol: str | None
    listing_status: str
    listed_from: str | None
    listed_to: str | None
    evidence_ids: tuple[str, ...]
    unavailable_reason: str | None

    def __post_init__(self) -> None:
        super().__post_init__()
        require(1900 <= self.contract_year <= 9999, "contract_year must be four digits")
        require(
            self.listing_status != "unknown_historical_listing" or self.symbol is None,
            "unknown historical listings cannot have an inferred symbol",
        )


@dataclass(frozen=True, kw_only=True)
class MarketObservation(StrictRecord):
    market_observation_id: str
    instrument_listing_id: str
    observed_at: str | None
    available_at: str | None
    field_type: str
    value: float | None
    currency: str | None
    unit: str | None
    source_artifact_id: str | None
    access_class: str
    executable_status: str
    unavailable_reason: str | None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.executable_status == "unavailable":
            require(self.value is None, "unavailable market observations cannot contain a value")
            require(bool(self.unavailable_reason), "unavailable market observations need a reason")


@dataclass(frozen=True, kw_only=True)
class ContractWindow(StrictRecord):
    contract_window_id: str
    contract_year: int
    index: str
    month: int
    observation_start: str
    observation_end: str
    valuation_date: str
    timing_status: str
    observed_start: str | None
    observed_end: str | None
    remaining_start: str | None
    remaining_end: str | None
    research_settlement_date: str
    settlement_timing_status: str
    exact_settlement_available: bool
    exact_settlement_unavailable_reason: str

    def __post_init__(self) -> None:
        super().__post_init__()
        require(self.index in {"HDD", "CDD"}, "index must be HDD or CDD")
        require(1 <= self.month <= 12, "month must be in 1..12")
        require(self.timing_status in {"future", "partial", "elapsed"}, "invalid timing_status")
        require(
            not self.exact_settlement_available
            and self.settlement_timing_status == "approximate_research_only",
            "frozen V1 windows may only expose approximate research settlement timing",
        )
