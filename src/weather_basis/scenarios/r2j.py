"""One-horizon adapter for daily R2j innovations."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .common import (
    CommonScenarioPlan,
    DailyScenarioPaths,
    _daily,
    _dates,
    _global_block_rows,
    _location_ids,
    _scenario_set,
)


@dataclass(frozen=True)
class R2JCommonHorizonAdapter:
    """Resample shared standardized-innovation blocks across the full horizon."""

    mean_block_days: int = 7

    def generate(
        self,
        *,
        history_dates: np.ndarray | pd.DatetimeIndex,
        standardized_residuals: np.ndarray,
        target_mean: np.ndarray,
        target_sigma: np.ndarray,
        location_ids: tuple[str, ...],
        plan: CommonScenarioPlan,
        data_vintage_id: str,
        model_spec_id: str,
        ar_coefficients: np.ndarray | None = None,
    ) -> DailyScenarioPaths:
        location_ids = _location_ids(location_ids)
        dates = _dates(history_dates)
        residuals = _daily(standardized_residuals, dates, location_ids)
        mean = _daily(target_mean, plan.dates, location_ids)
        sigma = _daily(target_sigma, plan.dates, location_ids)
        if np.any(sigma <= 0):
            raise ValueError("target sigma must be positive")
        valid = np.all(np.isfinite(residuals), axis=1)
        rng = np.random.default_rng(plan.seed)
        rows = [
            _global_block_rows(valid, len(plan.dates), rng, self.mean_block_days)
            for _ in range(plan.scenario_count)
        ]
        if ar_coefficients is None:
            values = np.stack([mean + sigma * residuals[row] for row in rows], axis=0)
        else:
            coefficients = np.asarray(ar_coefficients, dtype=float)
            if coefficients.ndim != 2 or coefficients.shape[0] != len(location_ids):
                raise ValueError("AR coefficients must have shape (locations, lags)")
            values = np.empty(
                (plan.scenario_count, len(plan.dates), len(location_ids)), dtype=float
            )
            state = np.zeros((coefficients.shape[1], plan.scenario_count, len(location_ids)))
            for day in range(len(plan.dates)):
                innovation = residuals[np.asarray(rows)[:, day]]
                residual = innovation.copy()
                for lag in range(coefficients.shape[1]):
                    residual += state[lag] * coefficients[None, :, lag]
                if coefficients.shape[1]:
                    state[1:] = state[:-1]
                    state[0] = residual
                values[:, day] = mean[day] + sigma[day] * residual
        ids = tuple(f"{plan.plan_id[:12]}-r2j-{i:05d}" for i in range(plan.scenario_count))
        scenario_set = _scenario_set(
            plan,
            scenario_ids=ids,
            location_ids=location_ids,
            scenario_type="physical_predictive",
            data_vintage_id=data_vintage_id,
            model_spec_ids=(model_spec_id, "r2j-common-horizon-v1"),
        )
        return DailyScenarioPaths(
            scenario_set=scenario_set, dates=plan.dates, location_ids=location_ids, values=values
        )


def r2j_common_horizon(**kwargs) -> DailyScenarioPaths:
    """Convenience adapter using the registered seven-day moving blocks."""
    return R2JCommonHorizonAdapter().generate(**kwargs)
