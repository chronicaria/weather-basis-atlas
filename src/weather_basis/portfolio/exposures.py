"""Transparent, versioned illustrative dollar-per-degree-day exposure losses."""

from __future__ import annotations

import numpy as np


def _finite(index: np.ndarray | float) -> np.ndarray:
    result = np.asarray(index, dtype=np.float64)
    if not np.isfinite(result).all():
        raise ValueError("index values must be finite")
    return result


def heating_shortfall(
    index: np.ndarray | float, budget: float, dollars_per_degree_day: float
) -> np.ndarray:
    """Loss from a heating index below budget: ``a * max(K - HDD, 0)``."""
    if dollars_per_degree_day < 0:
        raise ValueError("dollars_per_degree_day must be non-negative")
    return dollars_per_degree_day * np.maximum(budget - _finite(index), 0.0)


def cooling_overrun(
    index: np.ndarray | float,
    budget: float,
    dollars_per_degree_day: float,
    *,
    cap: float | None = None,
) -> np.ndarray:
    """Loss from a cooling index above budget, optionally with a declared dollar cap."""
    if dollars_per_degree_day < 0 or cap is not None and cap < 0:
        raise ValueError("dollars_per_degree_day and cap must be non-negative")
    result = dollars_per_degree_day * np.maximum(_finite(index) - budget, 0.0)
    return result if cap is None else np.minimum(result, cap)


def asymmetric_deviation(
    index: np.ndarray | float,
    budget: float,
    cold_dollars_per_degree_day: float,
    hot_dollars_per_degree_day: float,
) -> np.ndarray:
    """Piecewise-linear loss around a stated weather budget."""
    if cold_dollars_per_degree_day < 0 or hot_dollars_per_degree_day < 0:
        raise ValueError("loss slopes must be non-negative")
    deviation = _finite(index) - budget
    return cold_dollars_per_degree_day * np.maximum(
        -deviation, 0.0
    ) + hot_dollars_per_degree_day * np.maximum(deviation, 0.0)
