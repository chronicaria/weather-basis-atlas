"""Unit tests enforcing Weather Basis Atlas build plan Sections 6.2, 6.3, and 6.9."""

from __future__ import annotations

import numpy as np
import pytest

from weather_basis.hedge.metrics import es_lower, es_upper, he, pooled_metrics, rmse, worst
from weather_basis.hedge.ols import fit_at_origins
from weather_basis.hedge.rolling import rolling_residuals


def test_ols_uses_only_observations_strictly_before_origin() -> None:
    """Section 6.3: an origin's regression excludes its realized test season."""
    station = np.array([[0.0], [1.0], [2.0], [100.0]])
    county = np.array([[1.0], [3.0], [5.0], [-1000.0]])
    fit = fit_at_origins(county, station, min_train=np.array([3]))

    # The fit immediately before season three is y=1+2x.  Its outrageous test
    # outcome must not affect h or alpha.
    assert fit.n[3, 0, 0] == 3
    assert fit.h[3, 0, 0] == pytest.approx(2.0)
    assert fit.alpha[3, 0, 0] == pytest.approx(1.0)
    assert fit.train_r2[3, 0, 0] == pytest.approx(1.0)


def test_pairwise_missing_values_and_station_specific_minimum() -> None:
    """Section 6.2: complete pair observations and each station's minimum govern fits."""
    county = np.array([[0.0], [1.0], [np.nan], [3.0], [4.0]])
    stations = np.array([[0.0, 0.0], [1.0, np.nan], [2.0, 2.0], [3.0, 3.0], [4.0, 4.0]])
    fit = fit_at_origins(county, stations, min_train=np.array([4, 2]))

    # Before origin four, station 0 has three complete pairs but does not meet
    # its higher record-length requirement; station 1 has two and does.
    assert fit.n[4, 0, 0] == 3
    assert not fit.fit_mask[4, 0, 0]
    assert fit.n[4, 0, 1] == 2
    assert fit.fit_mask[4, 0, 1]


def test_rolling_output_masks_missing_current_anomalies_and_keeps_float32() -> None:
    """Section 6.3: residuals exist only for valid contemporaneous test observations."""
    county = np.array([[0.0], [1.0], [2.0], [3.0], [4.0]])
    stations = np.array([[0.0], [1.0], [2.0], [np.nan], [4.0]])
    result = rolling_residuals(county, stations, first_test=2, min_train=np.array([2]))

    assert result.resid.shape == (3, 1, 1)
    assert result.resid.dtype == np.float32
    assert result.test_mask[:, 0, 0].tolist() == [True, False, True]
    assert result.resid[0, 0, 0] == pytest.approx(0.0)
    assert np.isnan(result.resid[1, 0, 0])


def test_pooled_metrics_follow_hand_computed_definitions() -> None:
    """Section 6.3: HE, RMSE, tails, and worst season use exactly the test mask."""
    target = np.array([0.0, 2.0, 4.0, 6.0])
    residual = np.array([1.0, -2.0, np.nan, 4.0])

    # Valid target observations are 0, 2, 6; their centered sum of squares is
    # 56/3 and the residual sum of squares is 21.
    assert he(residual, target) == pytest.approx(1.0 - 21.0 / (56.0 / 3.0))
    assert rmse(residual) == pytest.approx(np.sqrt(7.0))
    assert es_lower(residual, level=0.90, minimum=3) == pytest.approx(-2.0)
    assert es_upper(residual, level=0.90, minimum=3) == pytest.approx(4.0)
    worst_value, worst_index = worst(residual)
    assert worst_value == pytest.approx(4.0)
    assert worst_index == 3

    metrics = pooled_metrics(residual[:, None, None], target[:, None])
    assert metrics.n_test[0, 0] == 3
    assert metrics.worst_index[0, 0] == 3


def test_metrics_use_conservative_zero_for_constant_target_and_es_minimum() -> None:
    """Section 6.3 and Decision 0003: a finite constant target has zero HE."""
    assert he(np.array([0.0, 0.0]), np.array([3.0, 3.0])) == 1.0
    assert np.isnan(es_upper(np.array([1.0, 2.0]), minimum=3))
    assert np.isnan(es_lower(np.array([1.0, 2.0]), minimum=3))
    value, index = worst(np.array([np.nan, np.nan]))
    assert np.isnan(value)
    assert index == -1


def test_known_linear_system_has_zero_residual_after_minimum_training() -> None:
    """Section 6.3: intercept OLS exactly recovers a noiseless hedge relationship."""
    station = np.arange(8.0)[:, None]
    county = 5.0 - 1.5 * station
    result = rolling_residuals(county, station, first_test=3, min_train=np.array([3]))
    assert np.all(result.test_mask)
    np.testing.assert_allclose(result.h[:, 0, 0], -1.5, rtol=0, atol=1e-6)
    np.testing.assert_allclose(result.alpha[:, 0, 0], 5.0, rtol=0, atol=1e-6)
    np.testing.assert_allclose(result.resid[:, 0, 0], 0.0, rtol=0, atol=1e-6)


@pytest.mark.parametrize("rho", [0.3, 0.5, 0.7, 0.9])
def test_expanding_protocol_recovers_correlation_squared(rho: float) -> None:
    """Section 6.9: a long fixed-seed Gaussian run recovers the population HE."""
    rng = np.random.default_rng(20260901)
    station = rng.normal(size=(3200, 1))
    county = rho * station + np.sqrt(1.0 - rho**2) * rng.normal(size=(3200, 1))
    result = rolling_residuals(county, station, first_test=200, min_train=np.array([200]))

    assert he(result.resid, county[200:])[0, 0] == pytest.approx(rho**2, abs=0.02)
