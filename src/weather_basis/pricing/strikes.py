"""Strike-grid construction independent of fitted distribution moments.

Section 8.2 requires the standardized and percentile grids to be based on the
trailing burn history, rather than the simulated pricing distribution.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class StrikeGrid:
    """A named integer strike grid and its burn-history positivity flag."""

    mode: str
    strikes: np.ndarray
    index_rarely_positive: bool = False


def _burn(values: np.ndarray) -> np.ndarray:
    x = np.asarray(values, dtype=np.float64).reshape(-1)
    x = x[np.isfinite(x)]
    if x.size == 0:
        raise ValueError("burn samples must contain at least one finite value")
    return x


def index_rarely_positive(burn: np.ndarray) -> bool:
    """Whether fewer than half of burn observations have a positive index."""
    x = _burn(burn)
    return bool(np.mean(x > 0.0) < 0.5)


def standardized_strikes(burn: np.ndarray, z_grid: np.ndarray) -> StrikeGrid:
    """Return ``max(0, round(mu + z sigma))`` strikes from the burn sample."""
    x = _burn(burn)
    z = np.asarray(z_grid, dtype=np.float64)
    if not np.isfinite(z).all():
        raise ValueError("z_grid must be finite")
    # ddof=0 describes the empirical burn distribution used by the protocol.
    strikes = np.maximum(0, np.rint(x.mean() + z * x.std(ddof=0))).astype(np.int64)
    return StrikeGrid("standardized", strikes, index_rarely_positive(x))


def percentile_strikes(burn: np.ndarray, percentile_grid: np.ndarray) -> StrikeGrid:
    """Return rounded burn quantile strikes for probabilities in [0, 1]."""
    x = _burn(burn)
    q = np.asarray(percentile_grid, dtype=np.float64)
    if not np.isfinite(q).all() or np.any((q < 0.0) | (q > 1.0)):
        raise ValueError("percentile_grid must lie in [0, 1]")
    strikes = np.maximum(0, np.rint(np.quantile(x, q, method="linear"))).astype(np.int64)
    return StrikeGrid("percentile", strikes, index_rarely_positive(x))


def absolute_strikes(strikes: np.ndarray) -> StrikeGrid:
    """Validate an explorer-supplied absolute integer strike grid."""
    k = np.asarray(strikes)
    if not np.isfinite(k).all() or np.any(k < 0) or not np.all(k == np.rint(k)):
        raise ValueError("absolute strikes must be non-negative integers")
    return StrikeGrid("absolute", k.astype(np.int64), False)
