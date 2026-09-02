"""Composition helpers for the R2 daily temperature model (sections 7.2--7.3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from weather_basis.models.residual import ARFit, LogVarFit, fit_ar, fit_seasonal_logvar, standardize
from weather_basis.models.seasonal_mean import (
    MonthBlocks,
    elapsed_days,
    fit_window,
    month_blocks,
    predict,
)


@dataclass(frozen=True)
class DailyFit:
    mean_coef: np.ndarray
    ar: ARFit
    logvar: LogVarFit
    z: np.ndarray
    fit_mask: np.ndarray


def fit_daily(
    panel: Any,
    *,
    fit_through: Any,
    mean_blocks_stats: MonthBlocks | None = None,
    mean_months: int = 480,
    residual_years: int = 30,
    ar_orders: tuple[int, ...] = (1, 2, 3, 5),
    logvar_harmonics: int = 2,
    logvar_epsilon: float = 1.0e-6,
) -> DailyFit:
    """Fit the registered mean, AR, and seasonal variance on trailing history."""

    values = np.asarray(getattr(panel, "values", panel), dtype=np.float64)
    dates = pd.DatetimeIndex(pd.to_datetime(panel.dates))
    through = pd.Timestamp(fit_through)
    if values.ndim != 2 or len(dates) != values.shape[0]:
        raise ValueError("panel values and dates must align")
    blocks = mean_blocks_stats if mean_blocks_stats is not None else month_blocks(panel)
    coef = fit_window(blocks, end_month=through, n_months=mean_months)
    mean = predict(coef, elapsed_days(dates))
    start = through - pd.DateOffset(years=residual_years)
    fit_mask = (dates >= start) & (dates <= through)
    e = values[fit_mask] - mean[fit_mask]
    ar = fit_ar(e, orders=ar_orders)
    doy = dates[fit_mask].dayofyear.to_numpy()
    logvar = fit_seasonal_logvar(
        ar.innovations,
        doy,
        harmonics=logvar_harmonics,
        epsilon=logvar_epsilon,
    )
    z = standardize(ar.innovations, logvar, doy)
    return DailyFit(mean_coef=coef, ar=ar, logvar=logvar, z=z, fit_mask=fit_mask)
