"""The expanding-window, rolling-origin hedge protocol (plan Section 6.3)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from weather_basis.hedge.ols import fit_at_origins


@dataclass(frozen=True)
class RollingResult:
    """Rolling OLS outputs for origins from ``first_test`` onward.

    ``fit_mask`` records a valid pre-origin regression; ``test_mask`` additionally
    requires a complete contemporaneous county and station anomaly.  Coefficients
    and residuals are float32 because these tensors are persisted by the atlas.
    """

    h: np.ndarray
    alpha: np.ndarray
    resid: np.ndarray
    train_r2: np.ndarray
    fit_mask: np.ndarray
    test_mask: np.ndarray
    train_n: np.ndarray


def rolling_residuals(
    a_c: np.ndarray,
    a_j: np.ndarray,
    *,
    first_test: int,
    min_train: np.ndarray,
) -> RollingResult:
    """Run the exact no-look-ahead OLS hedge protocol at each test origin.

    ``first_test`` is a zero-based position on the supplied season axis, rather
    than a calendar-year label.  Rows before it are not returned.
    """

    county = np.asarray(a_c, dtype=np.float64)
    station = np.asarray(a_j, dtype=np.float64)
    if county.ndim != 2 or station.ndim != 2:
        raise ValueError("a_c and a_j must both have shape (seasons, series)")
    if not 0 <= first_test <= county.shape[0]:
        raise ValueError("first_test must be an index on the season axis")

    fit = fit_at_origins(county, station, min_train=np.asarray(min_train))
    current_valid = np.isfinite(county[:, :, None]) & np.isfinite(station[:, None, :])
    test_mask_all = fit.fit_mask & current_valid
    residual_all = np.full(fit.h.shape, np.nan, dtype=np.float64)
    predicted = fit.alpha + fit.h * station[:, None, :]
    np.subtract(county[:, :, None], predicted, out=residual_all, where=test_mask_all)

    cut = slice(first_test, None)
    return RollingResult(
        h=fit.h[cut].astype(np.float32),
        alpha=fit.alpha[cut].astype(np.float32),
        resid=residual_all[cut].astype(np.float32),
        train_r2=fit.train_r2[cut].astype(np.float32),
        fit_mask=fit.fit_mask[cut],
        test_mask=test_mask_all[cut],
        train_n=fit.n[cut].astype(np.int32),
    )
