"""Weighted finite-scenario risk statistics shared by portfolio reporting and optimization."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _validated(losses: np.ndarray, weights: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    losses = np.asarray(losses, dtype=np.float64).reshape(-1)
    weights = np.asarray(weights, dtype=np.float64).reshape(-1)
    if losses.size == 0 or losses.size != weights.size or not np.isfinite(losses).all():
        raise ValueError("losses and weights must be finite aligned vectors")
    if not np.isfinite(weights).all() or np.any(weights < 0) or not np.isclose(weights.sum(), 1.0):
        raise ValueError("weights must be non-negative and sum to one")
    return losses, weights


def weighted_quantile(losses: np.ndarray, weights: np.ndarray, level: float) -> float:
    losses, weights = _validated(losses, weights)
    if not 0 <= level <= 1:
        raise ValueError("quantile level must be in [0, 1]")
    order = np.argsort(losses, kind="stable")
    return float(
        losses[order][
            np.searchsorted(np.cumsum(weights[order]), level, side="left").clip(max=losses.size - 1)
        ]
    )


def expected_shortfall(losses: np.ndarray, weights: np.ndarray, alpha: float = 0.90) -> float:
    """Weighted ES using the fractional-tail Rockafellar--Uryasev definition."""
    losses, weights = _validated(losses, weights)
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    # A weighted alpha-quantile is a minimizer of the finite RU objective.
    # This avoids materializing its otherwise quadratic scenario-loss matrix.
    threshold = weighted_quantile(losses, weights, alpha)
    return float(threshold + np.dot(weights, np.maximum(losses - threshold, 0.0)) / (1 - alpha))


@dataclass(frozen=True)
class RiskStats:
    mean: float
    variance: float
    standard_deviation: float
    quantile: float
    expected_shortfall: float
    threshold_exceedance_probability: float | None


def risk_statistics(
    losses: np.ndarray,
    weights: np.ndarray,
    *,
    alpha: float = 0.90,
    threshold: float | None = None,
) -> RiskStats:
    losses, weights = _validated(losses, weights)
    mean = float(np.dot(weights, losses))
    variance = float(np.dot(weights, (losses - mean) ** 2))
    return RiskStats(
        mean=mean,
        variance=variance,
        standard_deviation=float(np.sqrt(variance)),
        quantile=weighted_quantile(losses, weights, alpha),
        expected_shortfall=expected_shortfall(losses, weights, alpha),
        threshold_exceedance_probability=(
            None if threshold is None else float(np.dot(weights, losses > threshold))
        ),
    )
