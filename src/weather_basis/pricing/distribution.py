"""Fast, deterministic evaluators for empirical option distributions.

Section 8.1 of the build plan.  The class deliberately owns a sorted copy of
its input: callers may pass aligned simulation draws without having to
remember a separate sorting step, while equal observations retain their input
order (``kind='stable'``).
"""

from __future__ import annotations

import numpy as np


class SortedSamples:
    """An empirical distribution backed by sorted samples and float64 sums."""

    def __init__(self, values: np.ndarray) -> None:
        raw = np.asarray(values, dtype=np.float32)
        if raw.ndim != 1 or raw.size == 0:
            raise ValueError("values must be a non-empty one-dimensional array")
        if not np.isfinite(raw).all():
            raise ValueError("values must be finite")
        self.values = np.sort(raw, kind="stable")
        # Leading zero makes S_i exactly the sum of the first i observations.
        self.prefix = np.concatenate(([0.0], np.cumsum(self.values, dtype=np.float64)))
        self.prefix_sq = np.concatenate(
            ([0.0], np.cumsum(np.square(self.values, dtype=np.float64), dtype=np.float64))
        )

    @property
    def n(self) -> int:
        return int(self.values.size)

    def _indices(self, strikes: np.ndarray) -> tuple[np.ndarray, tuple[int, ...]]:
        k = np.asarray(strikes, dtype=np.float64)
        if not np.isfinite(k).all():
            raise ValueError("strikes must be finite")
        return np.searchsorted(self.values, k, side="right"), k.shape

    @staticmethod
    def _restore(value: np.ndarray, shape: tuple[int, ...]) -> np.ndarray:
        return np.asarray(value).reshape(shape)

    def call(self, K: np.ndarray, m: float) -> np.ndarray:
        """Return ``m * E[max(I-K, 0)]``, vectorized over ``K``."""
        idx, shape = self._indices(K)
        k = np.asarray(K, dtype=np.float64)
        tail_n = self.n - idx
        value = float(m) * ((self.prefix[-1] - self.prefix[idx]) - k * tail_n) / self.n
        return self._restore(value, shape)

    def put(self, K: np.ndarray, m: float) -> np.ndarray:
        """Return ``m * E[max(K-I, 0)]``, vectorized over ``K``."""
        idx, shape = self._indices(K)
        k = np.asarray(K, dtype=np.float64)
        value = float(m) * (k * idx - self.prefix[idx]) / self.n
        return self._restore(value, shape)

    def digital(self, K: np.ndarray) -> np.ndarray:
        """Return the empirical probability ``P(I > K)``."""
        idx, shape = self._indices(K)
        return self._restore((self.n - idx) / self.n, shape)

    def mean(self) -> float:
        """Return the empirical mean."""
        return float(self.prefix[-1] / self.n)

    def se_call(self, K: np.ndarray, m: float) -> np.ndarray:
        """Monte-Carlo standard error of :meth:`call` at each strike."""
        idx, shape = self._indices(K)
        k = np.asarray(K, dtype=np.float64)
        count = self.n - idx
        sum_x = self.prefix[-1] - self.prefix[idx]
        sum_x2 = self.prefix_sq[-1] - self.prefix_sq[idx]
        second = (sum_x2 - 2.0 * k * sum_x + np.square(k) * count) / self.n
        first = (sum_x - k * count) / self.n
        # The standard error estimates the sampling variability of the mean.
        # Bessel's correction is undefined for one draw, whose variability is 0.
        if self.n == 1:
            variance = np.zeros_like(first, dtype=np.float64)
        else:
            variance = np.maximum((second - np.square(first)) * self.n / (self.n - 1), 0.0)
        value = abs(float(m)) * np.sqrt(variance / self.n)
        return self._restore(value, shape)

    def quantiles(self, q: np.ndarray) -> np.ndarray:
        """Linear empirical quantiles, matching NumPy's documented default."""
        probs = np.asarray(q, dtype=np.float64)
        if not np.isfinite(probs).all() or np.any((probs < 0.0) | (probs > 1.0)):
            raise ValueError("quantiles must lie in [0, 1]")
        return np.quantile(self.values, probs, method="linear")
