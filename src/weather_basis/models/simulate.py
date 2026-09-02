"""Memory-bounded R2 simulation (plan Section 7.4)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BlockPlan:
    indices: np.ndarray
    starts: np.ndarray
    lengths: np.ndarray

    @property
    def M(self) -> int:
        return int(self.indices.shape[0])


def block_plan(
    rng: np.random.Generator,
    *,
    M: int,
    n_days: int,
    mean_block: float,
    candidate_days: np.ndarray,
) -> BlockPlan:
    """Create stationary-bootstrap history indices with geometric block lengths."""
    candidates = np.asarray(candidate_days, dtype=np.int64)
    if M < 0 or n_days < 0 or mean_block <= 0 or not candidates.size:
        raise ValueError("positive mean block and non-empty candidates are required")
    if np.any(candidates < 0):
        raise ValueError("candidate days must be non-negative")
    if n_days == 0:
        return BlockPlan(
            np.empty((M, 0), dtype=np.int32),
            np.empty((M, 0), dtype=np.int32),
            np.empty((M, 0), dtype=np.int32),
        )
    indices = np.empty((M, n_days), dtype=np.int32)
    starts_list: list[np.ndarray] = []
    lengths_list: list[np.ndarray] = []
    p = 1.0 / mean_block
    for row in range(M):
        starts: list[int] = []
        lengths: list[int] = []
        pos = 0
        while pos < n_days:
            start_index = int(rng.integers(candidates.size))
            start = int(candidates[start_index])
            length = min(int(rng.geometric(p)), n_days - pos)
            starts.append(start)
            lengths.append(length)
            # A plan must never reference a non-candidate day (particularly
            # important for R2j's complete-case intersection).  Consecutive
            # candidate positions retain calendar continuity in normal data;
            # wrap makes short synthetic histories well-defined too.
            indices[row, pos : pos + length] = candidates[
                (start_index + np.arange(length)) % candidates.size
            ]
            pos += length
        starts_list.append(np.asarray(starts, dtype=np.int32))
        lengths_list.append(np.asarray(lengths, dtype=np.int32))
    max_blocks = max(x.size for x in starts_list)
    starts = np.full((M, max_blocks), -1, dtype=np.int32)
    lengths = np.zeros((M, max_blocks), dtype=np.int32)
    for row, (s, length) in enumerate(zip(starts_list, lengths_list, strict=True)):
        starts[row, : s.size], lengths[row, : length.size] = s, length
    return BlockPlan(indices, starts, lengths)


def simulate_month(
    z_hist: np.ndarray,
    *,
    plan: BlockPlan,
    sigma: np.ndarray,
    ar: np.ndarray,
    mean: np.ndarray,
    init_state: np.ndarray | None,
    series_slice: slice,
    accumulate_mask: np.ndarray,
    index_fn: Callable[[np.ndarray], np.ndarray],
) -> np.ndarray:
    """Stream an AR simulation day by day and return monthly index samples.

    Arrays ``sigma`` and ``mean`` are day-by-series. ``z_hist`` is
    history-day-by-series; only the requested series slice is retained in the
    working state, so no path cube is allocated.
    """
    z = np.asarray(z_hist, dtype=float)[:, series_slice]
    sig, mu = (
        np.asarray(sigma, dtype=float)[:, series_slice],
        np.asarray(mean, dtype=float)[:, series_slice],
    )
    coeff = np.asarray(ar, dtype=float)[series_slice]
    mask = np.asarray(accumulate_mask, dtype=bool)
    if (
        sig.shape != mu.shape
        or sig.shape[0] != plan.indices.shape[1]
        or mask.shape != (sig.shape[0],)
    ):
        raise ValueError("daily dimensions must agree with the block plan")
    M, n_days = plan.indices.shape
    n_series = z.shape[1]
    max_p = coeff.shape[1]
    state = np.zeros((max_p, M, n_series), dtype=np.float64)
    if init_state is not None:
        initial = np.asarray(init_state, dtype=float)
        if initial.shape == (max_p, n_series):
            state[:] = initial[:, None, :]
        elif initial.shape == state.shape:
            state[:] = initial
        else:
            raise ValueError("init_state must be (p, series) or (p, M, series)")
    total = np.zeros((M, n_series), dtype=np.float64)
    for day in range(n_days):
        source = plan.indices[:, day]
        if np.any(source < 0) or np.any(source >= z.shape[0]):
            raise ValueError("block plan contains history index outside z_hist")
        innovations = z[source[:, None], np.arange(n_series)[None, :]] * sig[day][None, :]
        residual = innovations.copy()
        for lag in range(max_p):
            residual += state[lag] * coeff[None, :, lag]
        if max_p:
            state[1:] = state[:-1]
            state[0] = residual
        if mask[day]:
            total += index_fn(mu[day][None, :] + residual)
    return total.astype(np.float32)
