"""R1 trend plus Student-t index model (plan Section 7.1)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.stats import t as student_t


@dataclass(frozen=True)
class IndexParametricFit:
    intercept: float
    slope: float
    scale: float
    nu: float
    nobs: int

    def location(self, season: float) -> float:
        return self.intercept + self.slope * float(season)


def fit_index_parametric(
    values: np.ndarray,
    *,
    seasons: np.ndarray | None = None,
    window: int = 40,
    nu_floor: float = 4.0,
    nu_ceiling: float = 100.0,
) -> IndexParametricFit:
    """Fit OLS trend and jointly maximum-likelihood Student-t scale and df."""
    y = np.asarray(values, dtype=float)
    x = np.arange(y.size, dtype=float) if seasons is None else np.asarray(seasons, dtype=float)
    if x.shape != y.shape:
        raise ValueError("seasons and values must have equal shape")
    x, y = x[-window:], y[-window:]
    valid = np.isfinite(x) & np.isfinite(y)
    x, y = x[valid], y[valid]
    if y.size < 3:
        raise ValueError("at least three finite observations are required")
    intercept, slope = np.linalg.lstsq(np.c_[np.ones(y.size), x], y, rcond=None)[0]
    residual = y - intercept - slope * x
    mad = np.median(np.abs(residual - np.median(residual))) * 1.4826
    start_scale = max(float(mad), float(np.std(residual, ddof=1)), np.finfo(float).eps)

    def objective(theta: np.ndarray) -> float:
        scale, nu = np.exp(theta[0]), theta[1]
        return float(-np.sum(student_t.logpdf(residual / scale, df=nu) - np.log(scale)))

    result = minimize(
        objective,
        np.array([np.log(start_scale), max(nu_floor, min(10.0, nu_ceiling))]),
        method="L-BFGS-B",
        bounds=[(np.log(np.finfo(float).eps), None), (nu_floor, nu_ceiling)],
    )
    if not result.success or not np.isfinite(result.fun):
        scale, nu = start_scale, nu_floor
    else:
        scale, nu = float(np.exp(result.x[0])), float(result.x[1])
    return IndexParametricFit(float(intercept), float(slope), scale, nu, int(y.size))


def simulate_index_parametric(
    fit: IndexParametricFit, *, season: float, M: int, rng: np.random.Generator
) -> np.ndarray:
    """Draw censored-at-zero R1 predictive samples."""
    if M < 0:
        raise ValueError("M must be non-negative")
    draws = fit.location(season) + fit.scale * rng.standard_t(fit.nu, size=M)
    return np.maximum(draws, 0.0).astype(np.float32)
