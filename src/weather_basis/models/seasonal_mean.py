"""Fixed-basis seasonal-mean temperature model (plan section 7.2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

ORIGIN = pd.Timestamp("1951-01-01")
PERIOD_DAYS = 365.2425
# Half the inclusive donor span 1951-01-01 through 2026-06-30, in days.
FIXED_CENTER_DAYS = 13_787.0
FIXED_SCALE_DAYS = 13_787.0


@dataclass(frozen=True)
class TimeBasis:
    """The immutable donor basis used for every rolling fit."""

    origin: pd.Timestamp = ORIGIN
    center_days: float = FIXED_CENTER_DAYS
    scale_days: float = FIXED_SCALE_DAYS
    period_days: float = PERIOD_DAYS


DEFAULT_BASIS = TimeBasis()


@dataclass(frozen=True)
class MonthBlocks:
    """Per-calendar-month normal-equation blocks for all series."""

    gram: np.ndarray
    xty: np.ndarray
    yy: np.ndarray
    counts: np.ndarray
    months: pd.DatetimeIndex
    basis: TimeBasis


def elapsed_days(dates: Any, *, origin: pd.Timestamp = ORIGIN) -> np.ndarray:
    """Return elapsed calendar days from the fixed donor origin."""

    values = pd.DatetimeIndex(pd.to_datetime(dates))
    return (values - origin).total_seconds().to_numpy(dtype=np.float64) / 86_400.0


def design_matrix(t_days: np.ndarray, *, basis: TimeBasis = DEFAULT_BASIS) -> np.ndarray:
    """Return the eight fixed-basis regressors specified in D-61."""

    t = np.asarray(t_days, dtype=np.float64)
    tau = (t - basis.center_days) / basis.scale_days
    phase = 2.0 * np.pi * t / basis.period_days
    sin1, cos1 = np.sin(phase), np.cos(phase)
    return np.column_stack(
        (
            np.ones_like(t),
            tau,
            sin1,
            cos1,
            np.sin(2.0 * phase),
            np.cos(2.0 * phase),
            tau * sin1,
            tau * cos1,
        )
    )


def _panel_values_dates(panel: Any) -> tuple[np.ndarray, pd.DatetimeIndex]:
    values = np.asarray(getattr(panel, "values", panel), dtype=np.float64)
    dates = getattr(panel, "dates", None)
    if dates is None:
        raise TypeError("panel must provide a dates attribute")
    dates_index = pd.DatetimeIndex(pd.to_datetime(dates))
    if values.ndim != 2 or values.shape[0] != len(dates_index):
        raise ValueError("panel values must have shape (days, series) matching dates")
    return values, dates_index


def month_blocks(panel: Any, *, basis: TimeBasis = DEFAULT_BASIS) -> MonthBlocks:
    """Accumulate finite-observation normal equations by calendar month."""

    values, dates = _panel_values_dates(panel)
    labels = dates.to_period("M").to_timestamp()
    months = pd.DatetimeIndex(labels.unique()).sort_values()
    n_series = values.shape[1]
    shape = (len(months), n_series)
    gram = np.zeros((len(months), n_series, 8, 8), dtype=np.float64)
    xty = np.zeros((*shape, 8), dtype=np.float64)
    yy = np.zeros(shape, dtype=np.float64)
    counts = np.zeros(shape, dtype=np.int64)
    t = elapsed_days(dates, origin=basis.origin)
    x_all = design_matrix(t, basis=basis)

    for block, month in enumerate(months):
        rows = labels == month
        x, y = x_all[rows], values[rows]
        valid = np.isfinite(y)
        filled = np.where(valid, y, 0.0)
        xty[block] = np.einsum("di,dn->ni", x, filled, optimize=True)
        yy[block] = np.einsum("dn,dn->n", filled, filled, optimize=True)
        counts[block] = valid.sum(axis=0)
        gram[block] = np.einsum("di,dn,dj->nij", x, valid, x, optimize=True)
    return MonthBlocks(gram=gram, xty=xty, yy=yy, counts=counts, months=months, basis=basis)


def _month_timestamp(value: Any) -> pd.Timestamp:
    if hasattr(value, "year") and hasattr(value, "month"):
        return pd.Timestamp(year=int(value.year), month=int(value.month), day=1)
    return pd.Timestamp(value).to_period("M").to_timestamp()


def _raw_transform(basis: TimeBasis) -> np.ndarray:
    """Map fixed (tau) coefficients to raw-t basis coefficients."""

    c_over_s = basis.center_days / basis.scale_days
    transform = np.zeros((8, 8), dtype=np.float64)
    transform[0, 0], transform[0, 1] = 1.0, -c_over_s
    transform[1, 1] = 1.0 / basis.scale_days
    transform[2, 2], transform[2, 6] = 1.0, -c_over_s
    transform[3, 3], transform[3, 7] = 1.0, -c_over_s
    transform[4, 4] = transform[5, 5] = 1.0
    transform[6, 6] = transform[7, 7] = 1.0 / basis.scale_days
    return transform


def fit_window(blocks: MonthBlocks, *, end_month: Any, n_months: int = 480) -> np.ndarray:
    """Fit all series on up to ``n_months`` ending at ``end_month``.

    Coefficients are returned in raw-t order: ``1, t, sin, cos, sin2, cos2,
    t*sin, t*cos``.  Series without a full-rank fit receive NaNs.
    """

    if n_months < 1:
        raise ValueError("n_months must be positive")
    end = _month_timestamp(end_month)
    selected = np.flatnonzero(blocks.months <= end)
    if not len(selected):
        raise ValueError("end_month precedes all sufficient-statistic blocks")
    selected = selected[-n_months:]
    gram = blocks.gram[selected].sum(axis=0)
    xty = blocks.xty[selected].sum(axis=0)
    n = gram.shape[0]
    stable = np.full((n, 8), np.nan, dtype=np.float64)
    for series in range(n):
        if np.linalg.matrix_rank(gram[series]) == 8:
            try:
                stable[series] = np.linalg.solve(gram[series], xty[series])
            except np.linalg.LinAlgError:
                pass
    return stable @ _raw_transform(blocks.basis).T


def predict(coef: np.ndarray, t_days: np.ndarray, period_days: float = PERIOD_DAYS) -> np.ndarray:
    """Evaluate raw-t mean coefficients, returning ``(days, series)``."""

    beta = np.asarray(coef, dtype=np.float64)
    if beta.ndim == 1:
        beta = beta[None, :]
    if beta.ndim != 2 or beta.shape[1] != 8:
        raise ValueError("coef must have shape (series, 8)")
    t = np.asarray(t_days, dtype=np.float64)
    phase = 2.0 * np.pi * t / period_days
    x = np.column_stack(
        (
            np.ones_like(t),
            t,
            np.sin(phase),
            np.cos(phase),
            np.sin(2 * phase),
            np.cos(2 * phase),
            t * np.sin(phase),
            t * np.cos(phase),
        )
    )
    return x @ beta.T
