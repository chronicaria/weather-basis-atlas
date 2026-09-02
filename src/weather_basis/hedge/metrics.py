"""Pooled out-of-sample hedge metrics (plan Section 6.3)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PooledMetrics:
    """Metrics pooled along a test-season axis."""

    he: np.ndarray
    rmse: np.ndarray
    es_upper: np.ndarray
    es_lower: np.ndarray
    worst: np.ndarray
    worst_index: np.ndarray
    n_test: np.ndarray


def _axis(axis: int, ndim: int) -> int:
    if not -ndim <= axis < ndim:
        raise np.exceptions.AxisError(axis, ndim=ndim)
    return axis % ndim


def _aligned(values: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Broadcast county anomalies across a trailing station dimension if needed."""

    array = np.asarray(values, dtype=np.float64)
    if array.ndim == reference.ndim - 1:
        array = array[..., None]
    try:
        return np.broadcast_to(array, reference.shape)
    except ValueError as exc:
        raise ValueError("values cannot be broadcast to the residual shape") from exc


def _valid_resid(resid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    array = np.asarray(resid, dtype=np.float64)
    if array.ndim == 0:
        raise ValueError("resid must have at least one dimension")
    return array, np.isfinite(array)


def he(resid: np.ndarray, a_c: np.ndarray, *, axis: int = 0) -> np.ndarray:
    """Pooled hedge effectiveness, using the matching test-season anomalies.

    It is intentionally not lower-bounded: a bad hedge can have a negative
    effectiveness.  A finite but constant target is assigned zero effectiveness:
    there is no target variance for a station hedge to explain, and emitting zero
    keeps sparse CDD counties in the reported universe without producing unstable
    ratios from floating-point noise.
    """

    residual, finite_resid = _valid_resid(resid)
    target = _aligned(a_c, residual)
    valid = finite_resid & np.isfinite(target)
    target_valid = np.where(valid, target, 0.0)
    residual_valid = np.where(valid, residual, 0.0)
    count = np.sum(valid, axis=_axis(axis, residual.ndim), dtype=np.int64)
    mean = np.divide(
        np.sum(target_valid, axis=axis), count, out=np.full(count.shape, np.nan), where=count > 0
    )
    centered_ss = np.sum(
        np.where(valid, (target - np.expand_dims(mean, axis)) ** 2, 0.0), axis=axis
    )
    residual_ss = np.sum(residual_valid * residual_valid, axis=axis)
    result = np.full(count.shape, np.nan, dtype=np.float64)
    scale = np.sum(np.where(valid, target * target, 0.0), axis=axis)
    tolerance = np.maximum(np.finfo(np.float64).eps, 1.0e-12 * np.maximum(scale, 1.0))
    informative = (count >= 2) & (centered_ss > tolerance)
    np.divide(residual_ss, centered_ss, out=result, where=informative)
    effectiveness = 1.0 - result
    degenerate = (count > 0) & ~informative
    perfect = degenerate & (residual_ss <= tolerance)
    return np.where(perfect, 1.0, np.where(degenerate, 0.0, effectiveness))


def rmse(resid: np.ndarray, *, axis: int = 0) -> np.ndarray:
    """Root mean square residual over finite test seasons."""

    residual, valid = _valid_resid(resid)
    count = np.sum(valid, axis=axis, dtype=np.int64)
    ss = np.sum(np.where(valid, residual * residual, 0.0), axis=axis)
    mean_square = np.divide(ss, count, out=np.full(count.shape, np.nan), where=count > 0)
    return np.sqrt(mean_square)


def _expected_shortfall(
    resid: np.ndarray, *, level: float, minimum: int, upper: bool, axis: int
) -> np.ndarray:
    if not 0.0 < level < 1.0:
        raise ValueError("level must be strictly between zero and one")
    if minimum < 1:
        raise ValueError("minimum must be positive")
    values, finite = _valid_resid(resid)
    axis = _axis(axis, values.ndim)
    moved = np.moveaxis(values, axis, 0)
    valid_moved = np.moveaxis(finite, axis, 0)
    n = np.sum(valid_moved, axis=0, dtype=np.int64)
    if moved.shape[0] == 0:
        return np.full(n.shape, np.nan, dtype=np.float64)
    # Inf places missing values after every finite value.  Prefix sums then make
    # either tail a gather, without loops over county/station columns.
    ordered = np.sort(np.where(valid_moved, moved, np.inf), axis=0)
    prefix = np.cumsum(np.where(np.isfinite(ordered), ordered, 0.0), axis=0)
    k = np.ceil((1.0 - level) * n).astype(np.int64)
    k = np.maximum(k, 1)
    lower_sum = np.take_along_axis(prefix, (k - 1)[None, ...], axis=0)[0]
    start = n - k
    before_start = np.where(
        start > 0, np.take_along_axis(prefix, np.maximum(start - 1, 0)[None, ...], axis=0)[0], 0.0
    )
    total = np.where(
        n > 0, np.take_along_axis(prefix, np.maximum(n - 1, 0)[None, ...], axis=0)[0], 0.0
    )
    tail_sum = total - before_start if upper else lower_sum
    answer = np.divide(tail_sum, k, out=np.full(n.shape, np.nan), where=n >= minimum)
    return answer


def es_upper(
    resid: np.ndarray, *, level: float = 0.90, minimum: int = 3, axis: int = 0
) -> np.ndarray:
    """Mean of the largest ``ceil((1-level) * n)`` finite residuals."""

    return _expected_shortfall(resid, level=level, minimum=minimum, upper=True, axis=axis)


def es_lower(
    resid: np.ndarray, *, level: float = 0.90, minimum: int = 3, axis: int = 0
) -> np.ndarray:
    """Mean of the smallest ``ceil((1-level) * n)`` finite residuals."""

    return _expected_shortfall(resid, level=level, minimum=minimum, upper=False, axis=axis)


def worst(resid: np.ndarray, *, axis: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(max_abs_residual, index_along_axis)`` for finite residuals.

    An all-missing slice yields ``(nan, -1)``.  The index is positional on the
    supplied residual tensor; callers can map it to a season label.
    """

    values, finite = _valid_resid(resid)
    axis = _axis(axis, values.ndim)
    if values.shape[axis] == 0:
        shape = values.shape[:axis] + values.shape[axis + 1 :]
        return np.full(shape, np.nan), np.full(shape, -1, dtype=np.intp)
    magnitude = np.where(finite, np.abs(values), -np.inf)
    index = np.argmax(magnitude, axis=axis)
    value = np.take_along_axis(magnitude, np.expand_dims(index, axis), axis=axis).squeeze(axis)
    no_data = ~np.any(finite, axis=axis)
    return np.where(no_data, np.nan, value), np.where(no_data, -1, index)


def pooled_metrics(
    resid: np.ndarray,
    a_c: np.ndarray,
    *,
    level: float = 0.90,
    es_min_seasons: int = 3,
    axis: int = 0,
) -> PooledMetrics:
    """Compute all plan-specified pooled metrics on the same residual tensor."""

    residual, finite = _valid_resid(resid)
    target = _aligned(a_c, residual)
    count = np.sum(finite & np.isfinite(target), axis=axis, dtype=np.int64)
    worst_value, worst_index = worst(residual, axis=axis)
    return PooledMetrics(
        he=he(residual, target, axis=axis),
        rmse=rmse(residual, axis=axis),
        es_upper=es_upper(residual, level=level, minimum=es_min_seasons, axis=axis),
        es_lower=es_lower(residual, level=level, minimum=es_min_seasons, axis=axis),
        worst=worst_value,
        worst_index=worst_index,
        n_test=count,
    )
