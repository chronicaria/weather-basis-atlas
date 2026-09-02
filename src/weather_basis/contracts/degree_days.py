"""Degree-day transformations used by the local and station index definitions (Section 5.3)."""

from __future__ import annotations

import numpy as np


def daily_hdd(tbar_f: np.ndarray, base: float = 65.0) -> np.ndarray:
    """Heating degree days, calculated after temperature averaging and never rounded."""
    return np.maximum(float(base) - np.asarray(tbar_f), 0.0)


def daily_cdd(tbar_f: np.ndarray, base: float = 65.0) -> np.ndarray:
    """Cooling degree days, calculated after temperature averaging and never rounded."""
    return np.maximum(np.asarray(tbar_f) - float(base), 0.0)


def monthly_index(daily: np.ndarray, month_mask: np.ndarray) -> np.ndarray:
    """Sum daily index values over selected calendar days along the leading time axis."""
    values = np.asarray(daily)
    mask = np.asarray(month_mask, dtype=bool)
    if values.ndim == 0:
        raise ValueError("daily must have a leading day axis")
    if mask.ndim != 1 or len(mask) != values.shape[0]:
        raise ValueError("month_mask must be one-dimensional and match daily's leading axis")
    return values[mask].sum(axis=0)
