"""Vectorized expanding-window ordinary least-squares fits.

The atlas fits a county anomaly to each station anomaly at every origin.  This
module deliberately uses prefix moments: an origin never incorporates its own
outcome (or a later outcome).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class OLSFit:
    """OLS coefficients and diagnostics evaluated immediately before each season.

    Arrays have shape ``(seasons, counties, stations)``.  ``n`` is the number
    of complete county/station observations available before that origin.
    """

    h: np.ndarray
    alpha: np.ndarray
    train_r2: np.ndarray
    n: np.ndarray
    fit_mask: np.ndarray


def _validate_inputs(
    a_c: np.ndarray, a_j: np.ndarray, min_train: np.ndarray
) -> tuple[int, int, int]:
    if a_c.ndim != 2 or a_j.ndim != 2:
        raise ValueError("a_c and a_j must both be two-dimensional (seasons, series)")
    seasons, counties = a_c.shape
    if a_j.shape[0] != seasons:
        raise ValueError("a_c and a_j must have the same number of seasons")
    stations = a_j.shape[1]
    if min_train.shape != (stations,):
        raise ValueError("min_train must have one non-negative value per station")
    if np.any(min_train < 0):
        raise ValueError("min_train cannot contain negative values")
    return seasons, counties, stations


def fit_at_origins(a_c: np.ndarray, a_j: np.ndarray, *, min_train: np.ndarray) -> OLSFit:
    """Fit ``a_c = alpha + h * a_j`` using only observations before each origin.

    Missing observations are excluded pairwise.  The returned arrays include
    every possible origin; the first row consequently has no training data.
    Computation is vectorized over the county-by-station grid.
    """

    county = np.asarray(a_c, dtype=np.float64)
    station = np.asarray(a_j, dtype=np.float64)
    minimum = np.asarray(min_train)
    seasons, counties, stations = _validate_inputs(county, station, minimum)

    county_3d = county[:, :, None]
    station_3d = station[:, None, :]
    complete = np.isfinite(county_3d) & np.isfinite(station_3d)
    valid_county = np.where(complete, county_3d, 0.0)
    valid_station = np.where(complete, station_3d, 0.0)

    # Prefixes ending at (and excluding) the current season prevent look-ahead.
    def before_origin(values: np.ndarray) -> np.ndarray:
        cumulative = np.cumsum(values, axis=0, dtype=np.float64)
        return np.concatenate((np.zeros((1, counties, stations)), cumulative[:-1]), axis=0)

    n = before_origin(complete)
    sum_c = before_origin(valid_county)
    sum_j = before_origin(valid_station)
    sum_j2 = before_origin(valid_station * valid_station)
    sum_c2 = before_origin(valid_county * valid_county)
    sum_cj = before_origin(valid_county * valid_station)

    denominator = n * sum_j2 - sum_j * sum_j
    numerator = n * sum_cj - sum_j * sum_c
    min_mask = n >= minimum.reshape(1, 1, stations)
    finite_denominator = np.isfinite(denominator) & (denominator > 0.0)
    fit_mask = min_mask & finite_denominator

    h = np.full((seasons, counties, stations), np.nan, dtype=np.float64)
    np.divide(numerator, denominator, out=h, where=fit_mask)
    alpha = np.full_like(h, np.nan)
    np.divide(sum_c - h * sum_j, n, out=alpha, where=fit_mask)

    # R² for an intercept model is squared training correlation.  A constant
    # county target has undefined R² even when the slope denominator is valid.
    county_ss = n * sum_c2 - sum_c * sum_c
    r2_denominator = denominator * county_ss
    r2_mask = fit_mask & np.isfinite(r2_denominator) & (r2_denominator > 0.0)
    train_r2 = np.full_like(h, np.nan)
    np.divide(numerator * numerator, r2_denominator, out=train_r2, where=r2_mask)
    # Tiny floating point overshoots are not meaningful, unlike a negative R²
    # (which cannot occur for an intercept OLS in exact arithmetic).
    np.clip(train_r2, 0.0, 1.0, out=train_r2)

    return OLSFit(h=h, alpha=alpha, train_r2=train_r2, n=n, fit_mask=fit_mask)
