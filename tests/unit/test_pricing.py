"""Tests enforcing build-plan Sections 8.1, 8.3, and 8.4."""

import numpy as np
import pytest

from weather_basis.pricing.coherence import check_distribution, check_quote
from weather_basis.pricing.distribution import SortedSamples
from weather_basis.pricing.quotes import HedgeSpec, JointDraws, PayoffSpec, loaded_quote
from weather_basis.pricing.strikes import percentile_strikes, standardized_strikes


def test_sorted_samples_matches_direct_payoffs_and_parity() -> None:
    samples = SortedSamples(np.array([3.0, 0.0, 1.0, 3.0, 2.0], dtype=np.float32))
    strikes = np.array([0.0, 1.5, 3.0, 4.0])
    assert np.allclose(samples.call(strikes, 20), [36, 14, 0, 0])
    assert np.allclose(samples.put(strikes, 20), [0, 8, 24, 44])
    assert np.allclose(samples.digital(strikes), [0.8, 0.6, 0.0, 0.0])
    assert samples.mean() == pytest.approx(1.8)
    assert check_distribution(samples, strikes, 20).ok


def test_call_standard_error_matches_direct_sample_standard_error() -> None:
    values = np.array([0.0, 1.0, 2.0, 8.0], dtype=np.float32)
    samples = SortedSamples(values)
    direct = 20 * np.maximum(values - 1.5, 0)
    assert samples.se_call(np.array([1.5]), 20)[0] == pytest.approx(direct.std(ddof=1) / 2)


def test_strikes_use_burn_not_simulated_moments() -> None:
    burn = np.array([0, 2, 4, 6, 8], dtype=float)
    standardized = standardized_strikes(burn, np.array([-1, 0, 1]))
    assert standardized.mode == "standardized"
    assert standardized.strikes.tolist() == [1, 4, 7]
    assert percentile_strikes(burn, np.array([0.5, 0.8])).strikes.tolist() == [4, 6]


def test_loaded_quote_decomposes_and_uses_aligned_hedge() -> None:
    county = np.array([0.0, 1.0, 2.0, 5.0, 9.0])
    station = np.array([0.0, 0.5, 2.5, 5.5, 8.0])
    q = loaded_quote(
        PayoffSpec(strike=2, multiplier=20),
        JointDraws(county, station),
        HedgeSpec("ORD"),
        {"quotes": {"w": 0.5, "alpha": 0.8, "friction_ticks": 1}},
        lam_model=1.25,
    )
    assert q.expected_payout == q.mid
    assert q.bid <= q.mid <= q.ask
    assert q.residual_load_ask >= 0 and q.residual_load_bid >= 0
    assert q.h != 0
    assert check_quote(q).ok


def test_unavailable_station_falls_back_without_station_draws() -> None:
    q = loaded_quote(
        PayoffSpec(3),
        JointDraws(np.array([1.0, 3.0, 5.0]), None),
        HedgeSpec("ORD", station_model="unavailable", atlas_h=0.7),
        {"quotes": {}},
        0.0,
    )
    assert q.station_model == "unavailable"
    assert q.h == pytest.approx(0.7)
