"""Unit-level rolling CRPS tournament utilities (plan Section 7.6)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .scoring import unit_skill


@dataclass(frozen=True)
class SkillInterval:
    skill: float
    lower: float
    upper: float
    n_origins: int

    @property
    def adopted(self) -> bool:
        return bool(np.isfinite(self.skill) and self.skill > 0 and self.lower > 0)


def year_block_interval(
    crps_upper: np.ndarray,
    crps_lower: np.ndarray,
    *,
    B: int,
    level: float = 0.90,
    rng: np.random.Generator,
) -> SkillInterval:
    """Bootstrap paired origins, preserving all cells within an origin."""
    upper, lower = np.broadcast_arrays(
        np.asarray(crps_upper, dtype=float), np.asarray(crps_lower, dtype=float)
    )
    if upper.ndim == 0:
        raise ValueError("the first axis must be origins")
    finite_origins = np.any(
        np.isfinite(upper) & np.isfinite(lower), axis=tuple(range(1, upper.ndim))
    )
    upper, lower = upper[finite_origins], lower[finite_origins]
    n = upper.shape[0]
    point = unit_skill(upper, lower)
    if n == 0 or B <= 0:
        return SkillInterval(point, float("nan"), float("nan"), n)
    draws = np.empty(B, dtype=float)
    for b in range(B):
        sampled = rng.integers(0, n, size=n)
        draws[b] = unit_skill(upper[sampled], lower[sampled])
    alpha = (1 - level) / 2
    lo, hi = np.nanquantile(draws, [alpha, 1 - alpha])
    return SkillInterval(point, float(lo), float(hi), n)


def select_rung(r1_r0: SkillInterval, r2_r1: SkillInterval) -> str:
    """Sequential ladder selection: an upper rung needs positive excluded-zero skill."""
    if not r1_r0.adopted:
        return "R0"
    return "R2" if r2_r1.adopted else "R1"


def tournament_selection(
    scores: pd.DataFrame,
    *,
    B: int = 1000,
    level: float = 0.90,
    seed: int = 20260901,
    lock: Any | None = None,
) -> pd.DataFrame:
    """Aggregate score rows to (pair, state) and select the pre-registered rung.

    Required columns are pair, state, origin, rung and crps.  Origins are
    guarded before selection, and each bootstrap resamples years jointly over
    counties in the unit.
    """
    required = {"pair", "state", "origin", "rung", "crps"}
    missing = required - set(scores.columns)
    if missing:
        raise ValueError(f"scores missing columns: {sorted(missing)}")
    origins = scores["origin"].dropna().astype(int).unique()
    if lock is not None:
        lock.check(origins, selection=True)
    elif os.environ.get("WBA_UNLOCK_HOLDOUT") != "1" and np.any(
        (origins >= 2023) & (origins <= 2025)
    ):
        raise PermissionError(
            "holdout seasons are locked; pass HoldoutLock with an explicit unlock"
        )
    base = scores.pivot_table(
        index=["pair", "state", "origin"], columns="rung", values="crps", aggfunc="sum"
    )
    children = np.random.SeedSequence(seed).spawn(len(base.groupby(level=[0, 1], sort=True)))
    rows: list[dict[str, object]] = []
    for child, ((pair, state), frame) in zip(
        children, base.groupby(level=[0, 1], sort=True), strict=True
    ):
        data = frame.droplevel([0, 1]).sort_index()
        rng = np.random.default_rng(child)
        r1 = year_block_interval(
            data.get("R1", pd.Series(np.nan, index=data.index)).to_numpy(),
            data.get("R0", pd.Series(np.nan, index=data.index)).to_numpy(),
            B=B,
            level=level,
            rng=rng,
        )
        r2 = year_block_interval(
            data.get("R2", pd.Series(np.nan, index=data.index)).to_numpy(),
            data.get("R1", pd.Series(np.nan, index=data.index)).to_numpy(),
            B=B,
            level=level,
            rng=rng,
        )
        rows.append(
            {
                "pair": pair,
                "state": state,
                "rung_selected": select_rung(r1, r2),
                "skill_r1_r0": r1.skill,
                "skill_r2_r1": r2.skill,
                "lb_r1_r0": r1.lower,
                "ub_r1_r0": r1.upper,
                "lb_r2_r1": r2.lower,
                "ub_r2_r1": r2.upper,
                "n_origins": r1.n_origins,
            }
        )
    return pd.DataFrame(rows)
