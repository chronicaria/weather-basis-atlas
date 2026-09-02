"""R0 empirical burn distributions (plan Section 7.1)."""

from __future__ import annotations

import numpy as np


def burn_samples(
    index_history: np.ndarray,
    *,
    season: int | None = None,
    window: int = 30,
    normal: float | None = None,
) -> np.ndarray:
    """Return the trailing empirical index distribution for the target season.

    ``index_history`` is ordered by season.  When ``normal`` is supplied the
    historical anomalies are rebased on it; otherwise this is simply the
    trailing observed empirical distribution.  The latter is useful when the
    caller has already constructed the desired normal-plus-anomaly series.
    """
    values = np.asarray(index_history, dtype=float)
    if values.ndim != 1:
        raise ValueError("index_history must be one dimensional")
    stop = values.size if season is None else int(season)
    if not 0 <= stop <= values.size:
        raise ValueError("season must index a future observation")
    train = values[max(0, stop - window) : stop]
    train = train[np.isfinite(train)]
    if not train.size:
        return np.empty(0, dtype=np.float32)
    if normal is None:
        return np.sort(train.astype(np.float32))
    baseline = float(np.mean(train))
    return np.sort((float(normal) + train - baseline).clip(0).astype(np.float32))


def sample_burn(
    index_history: np.ndarray, *, M: int, rng: np.random.Generator, **kwargs: object
) -> np.ndarray:
    """Sample R0 with replacement; this intentionally preserves atoms."""
    if M < 0:
        raise ValueError("M must be non-negative")
    empirical = burn_samples(index_history, **kwargs)
    if not empirical.size:
        return np.full(M, np.nan, dtype=np.float32)
    return rng.choice(empirical, size=M, replace=True).astype(np.float32)
