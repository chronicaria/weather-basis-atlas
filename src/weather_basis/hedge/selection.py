"""Deterministic station-selection rules from plan section 6.4."""

from __future__ import annotations

import numpy as np


def nearest(county_xy: np.ndarray, station_xy: np.ndarray) -> np.ndarray:
    """Return the nearest station for each county using great-circle distance.

    Coordinates are ``(longitude, latitude)`` in decimal degrees, the convention
    used by the gazetteer and station registry.  Ties deliberately resolve to the
    lowest station index through :func:`numpy.argmin`.
    """
    counties = np.asarray(county_xy, dtype=float)
    stations = np.asarray(station_xy, dtype=float)
    if counties.ndim != 2 or stations.ndim != 2 or counties.shape[1] != 2 or stations.shape[1] != 2:
        raise ValueError("county_xy and station_xy must have shape (n, 2) as (lon, lat)")
    if not len(stations):
        raise ValueError("at least one station is required")
    lon_c, lat_c = np.deg2rad(counties[:, 0])[:, None], np.deg2rad(counties[:, 1])[:, None]
    lon_j, lat_j = np.deg2rad(stations[:, 0])[None, :], np.deg2rad(stations[:, 1])[None, :]
    dlat = lat_j - lat_c
    dlon = lon_j - lon_c
    a = np.sin(dlat / 2) ** 2 + np.cos(lat_c) * np.cos(lat_j) * np.sin(dlon / 2) ** 2
    return np.argmin(2 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0))), axis=1).astype(np.intp)


def highest_train_corr(train_corr: np.ndarray) -> np.ndarray:
    """Choose the valid station with the largest training correlation per origin.

    Invalid fits are represented by NaN and yield ``-1`` only when no candidate
    is valid.  This makes missingness explicit instead of silently selecting the
    first station, which is important in short station records.
    """
    corr = np.asarray(train_corr, dtype=float)
    if corr.ndim != 3:
        raise ValueError("train_corr must have shape (origins, counties, stations)")
    valid = np.isfinite(corr)
    chosen = np.argmax(np.where(valid, corr, -np.inf), axis=2).astype(np.intp)
    return np.where(valid.any(axis=2), chosen, -1)


def _he(residual: np.ndarray, exposure: np.ndarray) -> float:
    """Pooled hedge effectiveness on one already-aligned time series."""
    mask = np.isfinite(residual) & np.isfinite(exposure)
    if not np.any(mask):
        return np.nan
    r = residual[mask]
    a = exposure[mask]
    denominator = np.sum((a - a.mean()) ** 2)
    if denominator <= 0:
        return np.nan
    return float(1.0 - np.sum(r * r) / denominator)


def point_in_time_best(
    resid: np.ndarray,
    a_c: np.ndarray,
    train_r2: np.ndarray,
    first_test_j: np.ndarray,
    *,
    trailing: int = 10,
    min_oos: int = 5,
) -> np.ndarray:
    """Select a station using only information available before each origin.

    Once a county/station has ``min_oos`` earlier residuals, its score is pooled
    HE on its most recent ``trailing`` available earlier residuals.  Before any
    candidate is eligible, the common fallback is the contemporaneous training
    R². ``first_test_j`` is retained in this public contract as an auditable
    record-length input; unavailable pre-record observations must be NaN in
    ``resid`` and therefore cannot be selected.
    """
    residuals = np.asarray(resid, dtype=float)
    exposure = np.asarray(a_c, dtype=float)
    r2 = np.asarray(train_r2, dtype=float)
    starts = np.asarray(first_test_j)
    if residuals.ndim != 3:
        raise ValueError("resid must have shape (origins, counties, stations)")
    t_count, county_count, station_count = residuals.shape
    if exposure.shape != (t_count, county_count) or r2.shape != residuals.shape:
        raise ValueError("a_c and train_r2 shapes must agree with resid")
    if starts.shape != (station_count,):
        raise ValueError("first_test_j must have one entry per station")
    if trailing < 1 or min_oos < 1:
        raise ValueError("trailing and min_oos must be positive")

    result = np.full((t_count, county_count), -1, dtype=np.intp)
    for t in range(t_count):
        previous = residuals[:t]
        for c in range(county_count):
            scores = np.full(station_count, np.nan)
            eligible = np.zeros(station_count, dtype=bool)
            for j in range(station_count):
                finite = np.flatnonzero(
                    np.isfinite(previous[:, c, j]) & np.isfinite(exposure[:t, c])
                )
                if finite.size >= min_oos:
                    eligible[j] = True
                    scores[j] = _he(
                        previous[finite[-trailing:], c, j], exposure[finite[-trailing:], c]
                    )
            if eligible.any():
                valid = eligible & np.isfinite(scores) & np.isfinite(residuals[t, c])
                if valid.any():
                    result[t, c] = int(np.argmax(np.where(valid, scores, -np.inf)))
                continue
            valid = np.isfinite(r2[t, c]) & np.isfinite(residuals[t, c])
            if valid.any():
                result[t, c] = int(np.argmax(np.where(valid, r2[t, c], -np.inf)))
    return result
