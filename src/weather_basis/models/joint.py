"""R2j shared-plan helpers (plan Sections 7.1 and 7.4)."""

from __future__ import annotations

import numpy as np

from .simulate import BlockPlan, block_plan


def inclusion_mask(valid_z: np.ndarray) -> np.ndarray:
    """Return history days valid across every series included in R2j."""
    valid = np.asarray(valid_z, dtype=bool)
    if valid.ndim != 2:
        raise ValueError("valid_z must have shape (days, series)")
    return np.all(valid, axis=1)


def joint_block_plan(
    rng: np.random.Generator,
    *,
    M: int,
    n_days: int,
    mean_block: float,
    valid_z: np.ndarray,
) -> BlockPlan:
    """Make exactly one common calendar-day plan for all included series."""
    days = np.flatnonzero(inclusion_mask(valid_z))
    return block_plan(rng, M=M, n_days=n_days, mean_block=mean_block, candidate_days=days)


def residual_draws(county: np.ndarray, station: np.ndarray, hedge_ratio: float) -> np.ndarray:
    """Aligned R2j hedged-residual samples; input arrays must share paths."""
    c, j = np.asarray(county, dtype=float), np.asarray(station, dtype=float)
    if c.shape != j.shape:
        raise ValueError("county and station draws must be aligned")
    return c - float(hedge_ratio) * j
