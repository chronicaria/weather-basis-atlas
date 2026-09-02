"""Synthetic recovery tests for plan sections 7.2 and 7.3."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from weather_basis.models.residual import fit_ar, fit_seasonal_logvar, standardize
from weather_basis.models.seasonal_mean import (
    PERIOD_DAYS,
    elapsed_days,
    fit_window,
    month_blocks,
    predict,
)


def test_fixed_basis_month_blocks_recover_eight_parameter_mean() -> None:
    """Section 7.2: monthly sufficient statistics recover the fixed eight-term mean."""

    dates = pd.date_range("1951-01-01", "1990-12-31", freq="D")
    t = elapsed_days(dates)
    beta = np.array([[45.0, 0.0003, 12.0, -3.0, 1.2, 0.8, 1e-5, -2e-5]])
    y = predict(beta, t) + np.random.default_rng(3).normal(0.0, 0.15, (len(t), 1))
    blocks = month_blocks(SimpleNamespace(values=y, dates=dates))
    recovered = fit_window(blocks, end_month="1990-12", n_months=480)
    np.testing.assert_allclose(recovered, beta, rtol=0.0, atol=0.04)


def test_ar_selection_and_seasonal_standardization_recover_known_process() -> None:
    """Section 7.3: BIC finds AR(2) and scale matching standardizes innovations."""

    rng = np.random.default_rng(44)
    n_days, n_series = 12_000, 3
    doy = np.arange(n_days) % 365 + 1
    phase = 2 * np.pi * doy / PERIOD_DAYS
    sigma = np.exp(0.25 * np.sin(phase) - 0.15 * np.cos(2 * phase))
    e = np.zeros((n_days, n_series))
    innovation = rng.normal(size=(n_days, n_series)) * sigma[:, None]
    for i in range(2, n_days):
        e[i] = 0.55 * e[i - 1] - 0.22 * e[i - 2] + innovation[i]
    ar = fit_ar(e)
    assert np.all(ar.order == 2)
    np.testing.assert_allclose(ar.coef[:, :2], [[0.55, -0.22]] * n_series, atol=0.035)
    logvar = fit_seasonal_logvar(ar.innovations, doy)
    z = standardize(ar.innovations, logvar, doy)
    means = np.nanmean(z**2, axis=0)
    assert np.all((means >= 0.98) & (means <= 1.02))
