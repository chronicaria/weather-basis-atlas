"""Distribution scoring primitives (plan Section 7.5)."""

from __future__ import annotations

import numpy as np


def crps_from_samples(x_sorted: np.ndarray, y: float) -> float:
    """Empirical CRPS using the sorted-sample O(M) identity."""
    x = np.asarray(x_sorted, dtype=float)
    if x.ndim != 1 or not x.size:
        raise ValueError("x_sorted must be a non-empty vector")
    if not np.isfinite(y) or not np.all(np.isfinite(x)):
        return float("nan")
    if np.any(x[1:] < x[:-1]):
        raise ValueError("x_sorted must be ascending")
    m = x.size
    weights = 2.0 * np.arange(1, m + 1) - m - 1.0
    return float(np.mean(np.abs(x - y)) - np.dot(weights, x) / (m * m))


def pit(samples: np.ndarray, y: float) -> float:
    """Empirical probability integral transform, including ties."""
    x = np.asarray(samples, dtype=float)
    x = x[np.isfinite(x)]
    if not x.size or not np.isfinite(y):
        return float("nan")
    return float(np.count_nonzero(x <= y) / x.size)


def coverage(samples: np.ndarray, y: float, level: float) -> bool:
    """Whether y lies in the central predictive interval at ``level``."""
    if not 0.0 < level < 1.0:
        raise ValueError("level must be strictly between zero and one")
    x = np.asarray(samples, dtype=float)
    x = x[np.isfinite(x)]
    if not x.size or not np.isfinite(y):
        return False
    lo, hi = np.quantile(x, [(1 - level) / 2, (1 + level) / 2])
    return bool(lo <= y <= hi)


def brier(samples: np.ndarray, y: float, strike: float) -> float:
    """Brier score for the event index > strike."""
    x = np.asarray(samples, dtype=float)
    x = x[np.isfinite(x)]
    if not x.size or not np.isfinite(y):
        return float("nan")
    probability = np.count_nonzero(x > strike) / x.size
    return float((probability - float(y > strike)) ** 2)


def unit_skill(crps_upper: np.ndarray, crps_lower: np.ndarray) -> float:
    """Paired unit skill: one minus the ratio of pooled CRPS sums."""
    upper, lower = np.broadcast_arrays(
        np.asarray(crps_upper, dtype=float), np.asarray(crps_lower, dtype=float)
    )
    keep = np.isfinite(upper) & np.isfinite(lower)
    if not np.any(keep):
        return float("nan")
    denominator = float(np.sum(lower[keep]))
    return float("nan") if denominator == 0 else float(1.0 - np.sum(upper[keep]) / denominator)
