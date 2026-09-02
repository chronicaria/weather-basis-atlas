"""Trailing climatological normals and anomalies (plan Section 6.2)."""

from __future__ import annotations

import numpy as np


def _as_2d(x: np.ndarray) -> tuple[np.ndarray, bool]:
    values = np.asarray(x, dtype=float)
    if values.ndim == 1:
        return values[:, None], True
    if values.ndim != 2:
        raise ValueError("x must have shape (seasons,) or (seasons, series)")
    return values, False


def trailing_normal(x: np.ndarray, *, window: int = 30, min_prior: int) -> np.ndarray:
    """Return the mean of up to ``window`` available observations before each season.

    Missing observations are not observations of a zero index: they are skipped from
    the history, and both the normal and anomaly remain missing in their own season.
    This is important for excluded/provisional station months.
    """
    if window < 1:
        raise ValueError("window must be positive")
    if min_prior < 1:
        raise ValueError("min_prior must be positive")

    values, squeezed = _as_2d(x)
    out = np.full(values.shape, np.nan, dtype=float)
    for column in range(values.shape[1]):
        valid = np.flatnonzero(np.isfinite(values[:, column]))
        if valid.size <= min_prior:
            continue
        cumulative = np.concatenate(([0.0], np.cumsum(values[valid, column], dtype=float)))
        # The kth valid observation has k prior available observations.  The
        # normal uses the final min(window, k) of them.
        for k in range(min_prior, valid.size):
            start = max(0, k - window)
            out[valid[k], column] = (cumulative[k] - cumulative[start]) / (k - start)
    return out[:, 0] if squeezed else out


def anomaly(x: np.ndarray, *, window: int = 30, min_prior: int) -> np.ndarray:
    """Return index less its pre-season trailing normal."""
    values = np.asarray(x, dtype=float)
    return values - trailing_normal(values, window=window, min_prior=min_prior)


def prior_counts(x: np.ndarray, *, window: int = 30) -> np.ndarray:
    """Count available prior observations used by :func:`trailing_normal`."""
    if window < 1:
        raise ValueError("window must be positive")
    values, squeezed = _as_2d(x)
    out = np.zeros(values.shape, dtype=np.int16)
    for column in range(values.shape[1]):
        seen = 0
        for season, value in enumerate(values[:, column]):
            if np.isfinite(value):
                out[season, column] = min(window, seen)
                seen += 1
    return out[:, 0] if squeezed else out
