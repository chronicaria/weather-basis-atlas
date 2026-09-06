"""B04 fixtures for frozen support and non-fabricated contract facts."""

from datetime import date

import pytest

from weather_basis.contracts.calendar import Pair
from weather_basis.contracts.registry import load_contract_registry, load_frozen_vintage
from weather_basis.contracts.windows import resolve_contract_window


def test_frozen_vintage_exposes_variable_specific_support() -> None:
    vintage = load_frozen_vintage()
    support = {item.support_id: item for item in vintage.support}

    assert support["county-tavg-v1"].coverage_end == "2026-06"
    assert support["county-tmax-v1"].coherent_through == "2025-12"
    assert support["county-tmin-v1"].coherent_through == "2025-12"
    assert "Q flags" in support["station-tmean-v1"].qc_rule
    assert vintage.market_data_status == "absent_paid_or_registered_history"
    assert vintage.official_settlement_status == "absent_authorized_settlement_history"


def test_registry_separates_specification_listing_and_market_absence() -> None:
    registry = load_contract_registry()
    spec = registry.contract_spec("USW00014922", Pair("HDD", 1))
    window = registry.contract_window(Pair("HDD", 1), date(2026, 7, 1))
    listing = registry.instrument_listing(spec, window.contract_year, window)
    observation = registry.market_observation(listing, field_type="bid")

    assert spec.station_name == "Minneapolis-St. Paul International"
    assert spec.evidence_tier == "retained_documentary_transcription"
    assert listing.symbol is None
    assert listing.listing_status == "unknown_historical_listing"
    assert observation.value is None
    assert observation.executable_status == "unavailable"
    assert "zero price" in observation.unavailable_reason


def test_windows_resolve_next_contract_and_partial_boundaries() -> None:
    june = Pair("CDD", 6)
    next_june = resolve_contract_window(june, date(2026, 7, 1))
    partial = resolve_contract_window(june, date(2026, 6, 15), contract_year=2026)

    assert next_june.contract_year == 2027
    assert next_june.timing_status == "future"
    assert next_june.remaining_start == "2027-06-01"
    assert partial.timing_status == "partial"
    assert partial.observed_start == "2026-06-01"
    assert partial.observed_end == "2026-06-14"
    assert partial.remaining_start == "2026-06-15"
    assert partial.remaining_end == "2026-06-30"


def test_exact_settlement_timing_is_disabled_without_calendar_evidence() -> None:
    with pytest.raises(ValueError, match="exact settlement timing is unavailable"):
        resolve_contract_window(Pair("CDD", 6), date(2026, 5, 1), require_exact_settlement=True)
