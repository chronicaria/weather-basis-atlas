"""Joint season bootstrap for the hedge atlas (plan sections 6.5 and 6.8)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BootResult:
    """Bootstrap replicates; rows are draws and columns are counties/stations."""

    weights: np.ndarray
    he_pit: np.ndarray
    he_nearest: np.ndarray
    he_station: np.ndarray
    rmse_pit: np.ndarray
    rmse_nearest: np.ndarray
    rmse_station: np.ndarray

    def interval(self, values: np.ndarray, level: float = 0.90) -> tuple[np.ndarray, np.ndarray]:
        if not 0 < level < 1:
            raise ValueError("level must be between zero and one")
        q = (1 - level) / 2
        return np.nanquantile(values, q, axis=0), np.nanquantile(values, 1 - q, axis=0)


def _weights(t_count: int, B: int, seed: np.random.SeedSequence) -> np.ndarray:
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, t_count, size=(B, t_count), endpoint=False)
    out = np.zeros((B, t_count), dtype=np.int32)
    rows = np.repeat(np.arange(B), t_count)
    np.add.at(out, (rows, draws.ravel()), 1)
    return out


def _summary(
    weights: np.ndarray, residual: np.ndarray, exposure: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return HE and RMSE via count-matrix products without gathered tensors."""
    t_count, count = residual.shape
    valid = np.isfinite(residual) & np.isfinite(exposure)
    r = np.where(valid, residual, 0.0)
    a = np.where(valid, exposure, 0.0)
    n = weights @ valid.astype(np.float64)
    ssr = weights @ (r * r)
    sum_a = weights @ a
    sum_a2 = weights @ (a * a)
    sst = sum_a2 - np.divide(sum_a * sum_a, n, out=np.full_like(sum_a, np.nan), where=n > 0)
    scale = sum_a2
    tolerance = np.maximum(np.finfo(np.float64).eps, 1.0e-12 * np.maximum(scale, 1.0))
    informative = (n >= 2) & (sst > tolerance)
    ratio = np.divide(ssr, sst, out=np.full_like(ssr, np.nan), where=informative)
    degenerate = (n > 0) & ~informative
    he = np.where(degenerate & (ssr <= tolerance), 1.0, np.where(degenerate, 0.0, 1.0 - ratio))
    rmse = np.sqrt(np.divide(ssr, n, out=np.full_like(ssr, np.nan), where=n > 0))
    return he.reshape((weights.shape[0],) + residual.shape[1:]), rmse.reshape(
        (weights.shape[0],) + residual.shape[1:]
    )


def year_block_bootstrap(
    resid_pit: np.ndarray,
    resid_nearest: np.ndarray,
    resid_j: np.ndarray,
    a_c: np.ndarray,
    *,
    B: int,
    seed: np.random.SeedSequence,
    level: float = 0.90,
) -> BootResult:
    """Jointly resample seasons for point-in-time, nearest, and all stations.

    A single count matrix is deliberately shared by every statistic, preserving
    the cross-station and county dependence mandated by D-45.
    """
    pit = np.asarray(resid_pit, dtype=float)
    near = np.asarray(resid_nearest, dtype=float)
    stations = np.asarray(resid_j, dtype=float)
    exposure = np.asarray(a_c, dtype=float)
    if pit.ndim != 2 or near.shape != pit.shape or exposure.shape != pit.shape:
        raise ValueError("resid_pit, resid_nearest, and a_c must share shape (seasons, counties)")
    if stations.ndim != 3 or stations.shape[:2] != pit.shape:
        raise ValueError("resid_j must have shape (seasons, counties, stations)")
    if B < 1 or not 0 < level < 1:
        raise ValueError("B must be positive and level must be between zero and one")
    weights = _weights(pit.shape[0], B, seed)
    he_pit, rmse_pit = _summary(weights, pit, exposure)
    he_near, rmse_near = _summary(weights, near, exposure)
    expanded_exposure = np.broadcast_to(exposure[:, :, None], stations.shape)
    he_station, rmse_station = _summary(
        weights,
        stations.reshape(stations.shape[0], -1),
        expanded_exposure.reshape(stations.shape[0], -1),
    )
    return BootResult(
        weights,
        he_pit,
        he_near,
        he_station.reshape(B, *stations.shape[1:]),
        rmse_pit,
        rmse_near,
        rmse_station.reshape(B, *stations.shape[1:]),
    )


def stability(
    he_station: np.ndarray, best_pooled: np.ndarray, eligible: np.ndarray | None = None
) -> np.ndarray:
    """Frequency with which a bootstrap draw picks the supplied pooled winner."""
    he = np.asarray(he_station, dtype=float)
    best = np.asarray(best_pooled, dtype=int)
    if he.ndim != 3 or best.shape != (he.shape[1],):
        raise ValueError(
            "he_station must be (B, counties, stations); best_pooled must be (counties,)"
        )
    valid = np.isfinite(he)
    if eligible is not None:
        allowed = np.asarray(eligible, dtype=bool)
        if allowed.shape != best.shape + (he.shape[2],):
            raise ValueError("eligible must have shape (counties, stations)")
        valid &= allowed[None, :, :]
    chosen = np.argmax(np.where(valid, he, -np.inf), axis=2)
    present = valid.any(axis=2) & (best[None, :] >= 0)
    return np.divide(
        ((chosen == best[None, :]) & present).sum(axis=0),
        present.sum(axis=0),
        out=np.full(he.shape[1], np.nan),
        where=present.sum(axis=0) > 0,
    )
