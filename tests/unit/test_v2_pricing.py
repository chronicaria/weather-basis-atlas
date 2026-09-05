"""B06 availability and payoff-aware hedge hand cases."""

from datetime import date

import numpy as np
import pytest

from weather_basis.contracts.calendar import Pair
from weather_basis.pricing.bootstrap import mean_se, year_counts
from weather_basis.pricing.payoff_batch import (
    batch_quote_metrics,
    compare_independent_seed_metrics,
    payoff_batch,
)
from weather_basis.pricing.v2 import V2Payoff, payoff, price_v2, price_v2_legacy_arrays, select_asof


def test_call_put_and_caps_follow_hand_cashflows() -> None:
    values = np.array([1.0, 3.0, 7.0])
    np.testing.assert_allclose(payoff(values, V2Payoff("call", strike=3, multiplier=2)), [0, 0, 8])
    np.testing.assert_allclose(payoff(values, V2Payoff("put", strike=3, multiplier=2)), [4, 0, 0])
    np.testing.assert_allclose(
        payoff(values, V2Payoff("capped_call", strike=3, cap=2, multiplier=2)), [0, 0, 2]
    )


def test_july_about_june_resolves_next_year_and_needs_aligned_station_paths() -> None:
    decision = select_asof(
        valuation_date=date(2026, 7, 1),
        pair=Pair("CDD", 6),
        contract_year=None,
        observation_cutoff=date(2026, 7, 1),
        metadata_cutoff=date(2026, 7, 1),
        decision_eligible=np.array([True]),
        prior_scores=np.array([0.5]),
        nearest_station=0,
        station_ids=("s0",),
    )
    assert decision.contract_year == 2027
    price = price_v2_legacy_arrays(
        payoff_spec=V2Payoff("call", strike=2),
        county_paths=np.array([1.0, 3.0, 5.0]),
        station_paths=None,
        selection_asof=decision,
    )
    assert price.physical.amount == pytest.approx(80 / 3)
    assert price.hedged.status == "unavailable"
    assert price.hedged.reason == "missing_aligned_station_paths"
    assert price.market.status == "unavailable"


def test_nonlinear_ticket_recomputes_hedge_and_does_not_use_county_fallback() -> None:
    decision = select_asof(
        valuation_date=date(2026, 7, 1),
        pair=Pair("CDD", 7),
        contract_year=2027,
        observation_cutoff=date(2026, 7, 1),
        metadata_cutoff=date(2026, 7, 1),
        decision_eligible=np.array([True]),
        prior_scores=np.array([0.5]),
        nearest_station=0,
        station_ids=("s0",),
    )
    county, station = np.array([0.0, 2.0, 4.0, 8.0]), np.array([[0.0], [1.0], [3.0], [9.0]])
    call = price_v2_legacy_arrays(
        payoff_spec=V2Payoff("call", strike=3),
        county_paths=county,
        station_paths=station,
        selection_asof=decision,
    )
    linear = price_v2_legacy_arrays(
        payoff_spec=V2Payoff("linear", entry_level=0),
        county_paths=county,
        station_paths=station,
        selection_asof=decision,
    )
    assert call.hedged.status == "available"
    assert call.hedge_ratio != pytest.approx(linear.hedge_ratio)


def test_no_current_candidate_remains_unavailable_without_reselection() -> None:
    decision = select_asof(
        valuation_date=date(2026, 7, 1),
        pair=Pair("CDD", 7),
        contract_year=2027,
        observation_cutoff=date(2026, 7, 1),
        metadata_cutoff=date(2026, 7, 1),
        decision_eligible=np.array([False]),
        prior_scores=np.array([0.5]),
        nearest_station=0,
        station_ids=("s0",),
    )
    price = price_v2_legacy_arrays(
        payoff_spec=V2Payoff("put", strike=2),
        county_paths=np.array([1.0, 3.0]),
        station_paths=np.array([[1.0], [3.0]]),
        selection_asof=decision,
    )
    assert decision.choice_station_index == -1
    assert price.physical.status == "available"
    assert price.hedged.reason == "no_eligible_candidate"


def test_same_length_mismatched_scenario_ids_are_rejected() -> None:
    decision = select_asof(
        valuation_date=date(2026, 7, 1),
        pair=Pair("CDD", 7),
        contract_year=2027,
        observation_cutoff=date(2026, 7, 1),
        metadata_cutoff=date(2026, 7, 1),
        decision_eligible=np.array([True]),
        prior_scores=np.array([0.5]),
        nearest_station=0,
        station_ids=("s0",),
    )
    with pytest.raises(ValueError, match="scenario IDs"):
        price_v2(
            payoff_spec=V2Payoff("call", strike=1),
            county_paths=np.array([1.0, 2.0]),
            station_paths=np.array([[1.0], [2.0]]),
            selection_asof=decision,
            county_scenario_ids=("a", "b"),
            station_scenario_ids=("b", "a"),
            station_entity_ids=("s0",),
        )


def test_price_separates_physical_and_declared_load_once() -> None:
    decision = select_asof(
        valuation_date=date(2026, 7, 1),
        pair=Pair("CDD", 7),
        contract_year=2027,
        observation_cutoff=date(2026, 7, 1),
        metadata_cutoff=date(2026, 7, 1),
        decision_eligible=np.array([True]),
        prior_scores=np.array([0.5]),
        nearest_station=0,
        station_ids=("s0",),
    )
    price = price_v2(
        payoff_spec=V2Payoff("call", strike=2, multiplier=10),
        county_paths=np.array([1.0, 3.0, 5.0]),
        station_paths=np.array([[1.0], [3.0], [5.0]]),
        selection_asof=decision,
        model_load=1.25,
        county_scenario_ids=("a", "b", "c"),
        station_scenario_ids=("a", "b", "c"),
        station_entity_ids=("s0",),
    )
    assert price.physical.amount == pytest.approx(40 / 3)
    assert price.hedged.amount == pytest.approx(price.physical.amount)
    assert price.model_load.amount == pytest.approx(1.25)
    assert price.loaded.amount == pytest.approx(price.physical.amount + 1.25)
    assert price.loaded.method == "physical_expected_payout_plus_declared_model_load"


def test_missing_load_is_explicitly_unavailable_not_zero() -> None:
    decision = select_asof(
        valuation_date=date(2026, 7, 1),
        pair=Pair("CDD", 7),
        contract_year=2027,
        observation_cutoff=date(2026, 7, 1),
        metadata_cutoff=date(2026, 7, 1),
        decision_eligible=np.array([False]),
        prior_scores=np.array([0.5]),
        nearest_station=0,
        station_ids=("s0",),
    )
    price = price_v2_legacy_arrays(
        payoff_spec=V2Payoff("call", strike=2),
        county_paths=np.array([1.0, 3.0]),
        station_paths=None,
        selection_asof=decision,
    )
    assert price.physical.status == "available"
    assert price.model_load.status == "unavailable"
    assert price.model_load.reason == "missing_model_load_assumption"
    assert price.loaded.status == "unavailable"


def test_batched_quotes_match_unbatched_reference_and_reuse_counts() -> None:
    county = np.array([1.0, 3.0, 4.0, 8.0])
    station = np.array([0.0, 2.0, 5.0, 9.0])
    burn = np.array([0.0, 2.0, 4.0, 5.0, 9.0])
    specs = (
        V2Payoff("call", strike=3, multiplier=2),
        V2Payoff("put", strike=3, multiplier=2),
        V2Payoff("capped_call", strike=3, cap=4, multiplier=2),
    )
    counts = year_counts(len(burn), 31, np.random.SeedSequence(17))
    actual = batch_quote_metrics(county, station, burn, specs, counts)
    reference_payoffs = np.stack([payoff(county, spec) for spec in specs])
    centered_station = station - station.mean()
    reference_ratio = np.array(
        [
            ((ticket - ticket.mean()) @ centered_station) / (centered_station @ centered_station)
            for ticket in reference_payoffs
        ]
    )
    reference_residual = reference_payoffs - reference_ratio[:, None] * centered_station
    reference_load = mean_se(np.stack([payoff(burn, spec) for spec in specs]), counts)
    np.testing.assert_allclose(actual["expected_payout"], reference_payoffs.mean(axis=1))
    np.testing.assert_allclose(actual["hedge_ratio"], reference_ratio)
    np.testing.assert_allclose(actual["hedged_expected_payout"], reference_residual.mean(axis=1))
    np.testing.assert_allclose(actual["hedged_expected_payout"], actual["expected_payout"])
    np.testing.assert_allclose(actual["hedged_expected_payout_se"], actual["expected_payout_se"])
    np.testing.assert_allclose(actual["model_load_se"], reference_load)
    assert payoff_batch(county, specs).shape == (3, 4)


def test_independent_seed_comparison_uses_independent_mean_uncertainty() -> None:
    primary = {
        "expected_payout": np.array([10.0]),
        "expected_payout_se": np.array([1.0]),
        "hedged_expected_payout": np.array([9.0]),
        "hedged_expected_payout_se": np.array([0.5]),
        "model_load_se": np.array([0.2]),
        "hedge_ratio": np.array([0.8]),
        "residual_es_95": np.array([12.0]),
    }
    secondary = {key: value.copy() for key, value in primary.items()}
    secondary["expected_payout"] += 2.0
    report = compare_independent_seed_metrics(primary, secondary, sigma=2)
    assert report["status"] == "passed"
    secondary["hedged_expected_payout"] += 2.0
    assert compare_independent_seed_metrics(primary, secondary, sigma=2)["status"] == "failed"
