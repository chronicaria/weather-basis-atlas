"""Autoregressive residual and seasonal-volatility fits (plan section 7.3)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ARFit:
    coef: np.ndarray
    order: np.ndarray
    bic: np.ndarray
    innovations: np.ndarray
    valid: np.ndarray


@dataclass(frozen=True)
class LogVarFit:
    coef: np.ndarray
    scale: np.ndarray
    harmonics: int = 2


def fit_ar(e: np.ndarray, *, orders: tuple[int, ...] = (1, 2, 3, 5)) -> ARFit:
    """Choose a zero-intercept AR order by BIC on the common t > max(p) sample."""

    residuals = np.asarray(e, dtype=np.float64)
    if residuals.ndim != 2:
        raise ValueError("e must have shape (days, series)")
    if not orders or min(orders) < 1:
        raise ValueError("orders must be positive")
    max_order = max(orders)
    if residuals.shape[0] <= max_order:
        raise ValueError("not enough observations for requested AR orders")
    n_days, n_series = residuals.shape
    target = residuals[max_order:]
    lags = np.stack(
        [residuals[max_order - lag : n_days - lag] for lag in range(1, max_order + 1)],
        axis=2,
    )
    valid = np.isfinite(target) & np.isfinite(lags).all(axis=2)
    coef = np.zeros((n_series, max_order), dtype=np.float64)
    order_out = np.zeros(n_series, dtype=np.int64)
    bic_out = np.full(n_series, np.nan)
    innovations = np.full_like(residuals, np.nan)
    tiny = np.finfo(np.float64).tiny
    for series in range(n_series):
        mask = valid[:, series]
        n_obs = int(mask.sum())
        if n_obs <= max_order:
            continue
        y = target[mask, series]
        best: tuple[float, int, np.ndarray, np.ndarray] | None = None
        for p in orders:
            x = lags[mask, series, :p]
            beta, *_ = np.linalg.lstsq(x, y, rcond=None)
            err = y - x @ beta
            rss = float(err @ err)
            bic = n_obs * np.log(max(rss / n_obs, tiny)) + p * np.log(n_obs)
            if best is None or bic < best[0]:
                best = (bic, p, beta, err)
        assert best is not None
        bic_out[series], order_out[series] = best[0], best[1]
        coef[series, : best[1]] = best[2]
        innovations[max_order + np.flatnonzero(mask), series] = best[3]
    return ARFit(coef=coef, order=order_out, bic=bic_out, innovations=innovations, valid=valid)


def _logvar_design(doy: np.ndarray, harmonics: int) -> np.ndarray:
    if harmonics != 2:
        raise ValueError("the registered model uses exactly two harmonics")
    day = np.asarray(doy, dtype=np.float64)
    phase = 2.0 * np.pi * day / 365.2425
    return np.column_stack(
        (np.ones_like(day), np.sin(phase), np.cos(phase), np.sin(2 * phase), np.cos(2 * phase))
    )


def fit_seasonal_logvar(
    e_ar: np.ndarray,
    doy: np.ndarray,
    *,
    harmonics: int = 2,
    epsilon: float = 1.0e-6,
) -> LogVarFit:
    """Fit two-harmonic log variance and scale-match it to innovations."""

    e = np.asarray(e_ar, dtype=np.float64)
    if e.ndim != 2:
        raise ValueError("e_ar must have shape (days, series)")
    if len(doy) != e.shape[0]:
        raise ValueError("doy length must match e_ar days")
    x = _logvar_design(doy, harmonics)
    coef = np.full((e.shape[1], x.shape[1]), np.nan)
    scale = np.full(e.shape[1], np.nan)
    if epsilon <= 0:
        raise ValueError("epsilon must be positive")
    for series in range(e.shape[1]):
        valid = np.isfinite(e[:, series])
        if int(valid.sum()) <= x.shape[1]:
            continue
        beta, *_ = np.linalg.lstsq(x[valid], np.log(e[valid, series] ** 2 + epsilon), rcond=None)
        fitted = x[valid] @ beta
        c2 = np.mean(e[valid, series] ** 2 / np.exp(fitted))
        coef[series] = beta
        scale[series] = np.sqrt(c2)
    return LogVarFit(coef=coef, scale=scale, harmonics=harmonics)


def seasonal_sigma(fit: LogVarFit, doy: np.ndarray) -> np.ndarray:
    """Evaluate the scale-matched seasonal standard deviation."""

    x = _logvar_design(doy, fit.harmonics)
    return np.exp(0.5 * (x @ fit.coef.T)) * fit.scale


def standardize(e_ar: np.ndarray, fit: LogVarFit, doy: np.ndarray) -> np.ndarray:
    """Return standardized innovations; finite fitted values have mean z² of one."""

    e = np.asarray(e_ar, dtype=np.float64)
    sigma = seasonal_sigma(fit, doy)
    out = np.full_like(e, np.nan)
    valid = np.isfinite(e) & np.isfinite(sigma) & (sigma > 0)
    out[valid] = e[valid] / sigma[valid]
    return out
