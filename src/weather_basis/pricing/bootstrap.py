"""Reusable annual-bootstrap multiplicities for bounded quote batches."""

from __future__ import annotations

import numpy as np


def year_counts(n: int, B: int, seed: np.random.SeedSequence) -> np.ndarray:
    if n < 1 or B < 2:
        raise ValueError("n >= 1 and B >= 2 required")
    draws = np.random.default_rng(seed).integers(0, n, size=(B, n))
    counts = np.zeros((B, n), dtype=np.int32)
    np.add.at(counts, (np.arange(B)[:, None], draws), 1)
    return counts


def mean_se(payoffs: np.ndarray, counts: np.ndarray) -> np.ndarray:
    values = np.asarray(payoffs, dtype=np.float64)
    multiplicities = np.asarray(counts, dtype=np.float64)
    if values.ndim == 1:
        values = values[None, :]
    if values.ndim != 2 or not values.shape[1] or not np.isfinite(values).all():
        raise ValueError("payoffs must be a finite (tickets, observations) matrix")
    if (
        multiplicities.ndim != 2
        or multiplicities.shape[1] != values.shape[1]
        or multiplicities.shape[0] < 2
        or not np.isfinite(multiplicities).all()
        or (multiplicities < 0).any()
        or (multiplicities.sum(axis=1) == 0).any()
    ):
        raise ValueError("counts must be non-negative bootstrap multiplicities aligned to payoffs")
    means = multiplicities @ values.T / multiplicities.sum(axis=1, keepdims=True)
    return means.std(axis=0, ddof=1)
