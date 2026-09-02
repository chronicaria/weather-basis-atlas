"""Terminal cash flows for the synthetic degree-day products (Section 5.3, D-33)."""

from __future__ import annotations

import numpy as np


def _cap(payoff: np.ndarray, cap: float | np.ndarray | None) -> np.ndarray:
    if cap is None:
        return payoff
    return np.minimum(payoff, cap)


def call(
    index: np.ndarray | float,
    strike: np.ndarray | float,
    multiplier: float = 20.0,
    *,
    cap: float | np.ndarray | None = None,
) -> np.ndarray:
    """European call terminal cash flow: ``m * max(I - K, 0)``."""
    if multiplier < 0:
        raise ValueError("multiplier must be non-negative")
    payoff = float(multiplier) * np.maximum(np.asarray(index) - np.asarray(strike), 0.0)
    return _cap(payoff, cap)


def put(
    index: np.ndarray | float,
    strike: np.ndarray | float,
    multiplier: float = 20.0,
    *,
    cap: float | np.ndarray | None = None,
) -> np.ndarray:
    """European put terminal cash flow: ``m * max(K - I, 0)``."""
    if multiplier < 0:
        raise ValueError("multiplier must be non-negative")
    payoff = float(multiplier) * np.maximum(np.asarray(strike) - np.asarray(index), 0.0)
    return _cap(payoff, cap)


def futures(
    index: np.ndarray | float,
    futures_level: np.ndarray | float,
    multiplier: float = 20.0,
    *,
    cap: float | np.ndarray | None = None,
) -> np.ndarray:
    """Long futures terminal cash flow: ``m * (I - F)``."""
    if multiplier < 0:
        raise ValueError("multiplier must be non-negative")
    payoff = float(multiplier) * (np.asarray(index) - np.asarray(futures_level))
    return _cap(payoff, cap)
