"""Registered Section 7.7 R2 sensitivity table on the 18-county station subset.

This module deliberately leaves the production draw/quote paths untouched.
It reruns the daily model only for counties containing the 13 CME and five
Nebraska stations, then writes a compact table for the methodology page.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

from weather_basis.contracts.calendar import PAIRS, Pair
from weather_basis.contracts.degree_days import daily_cdd, daily_hdd
from weather_basis.models.daily import DailyFit, fit_daily
from weather_basis.models.joint import joint_block_plan
from weather_basis.models.residual import seasonal_sigma
from weather_basis.models.run_daily import _candidate_days, _combined_panel, _horizon, _target_year
from weather_basis.models.seasonal_mean import elapsed_days, month_blocks, predict
from weather_basis.models.simulate import simulate_month


@dataclass(frozen=True)
class SensitivitySpec:
    """One pre-registered, one-at-a-time perturbation of the R2 baseline."""

    dimension: str
    value: int


def sensitivity_specs() -> tuple[SensitivitySpec, ...]:
    """Return exactly the Section 7.7 sensitivity grid, including baseline levels."""
    return tuple(
        SensitivitySpec(dimension, value)
        for dimension, values in (
            ("mean_window_years", (30, 40, -1)),
            ("mean_harmonics", (1, 2, 3)),
            ("mean_block_days", (5, 7, 10)),
            ("residual_window_years", (20, 30, 40)),
        )
        for value in values
    )


def _cfg_value(cfg: Any, section: str, name: str, default: Any) -> Any:
    group = getattr(cfg, section, None)
    return getattr(group, name, default) if group is not None else default


def _subset(root: Path) -> tuple[SimpleNamespace, np.ndarray]:
    """Return exactly the 18 mapped station counties, in registry order."""
    panel, labels = _combined_panel(root)
    registry = pd.read_csv(root / "data/metadata/station_registry.csv", dtype={"ghcnd_id": str})
    counties = pd.read_csv(root / "data/contracts/station_county.csv", dtype=str)
    merged = registry[["ghcnd_id"]].merge(counties[["ghcnd_id", "county_fips"]], on="ghcnd_id")
    if len(merged) != 18 or merged["county_fips"].duplicated().any():
        raise ValueError("Section 7.7 requires 18 distinct station-county mappings")
    positions = {str(fips): index for index, fips in enumerate(labels)}
    fips = merged["county_fips"].str.zfill(5).to_numpy(dtype="U5")
    if any(item not in positions for item in fips):
        raise ValueError("a registered sensitivity county is absent from the county panel")
    index = np.asarray([positions[item] for item in fips], dtype=int)
    return SimpleNamespace(values=np.asarray(panel.values)[:, index], dates=panel.dates), fips


def _harmonic_design(days: np.ndarray, harmonics: int) -> np.ndarray:
    """Mean sensitivity design: fixed trend plus 1/2/3 annual harmonic pairs."""
    if harmonics not in (1, 2, 3):
        raise ValueError("mean harmonics must be one of 1, 2, 3")
    t = np.asarray(days, dtype=float)
    phase = 2 * np.pi * t / 365.2425
    terms = [np.ones_like(t), t]
    for harmonic in range(1, harmonics + 1):
        terms.extend((np.sin(harmonic * phase), np.cos(harmonic * phase)))
    # The registered trend interaction remains first-harmonic only.
    terms.extend((t * np.sin(phase), t * np.cos(phase)))
    return np.column_stack(terms)


def _harmonic_mean_fit(
    panel: Any, through: pd.Timestamp, years: int, harmonics: int
) -> tuple[np.ndarray, np.ndarray]:
    """Fit the variable-harmonic seasonal mean for the small sensitivity subset."""
    dates = pd.DatetimeIndex(pd.to_datetime(panel.dates))
    mask = (dates <= through) & (dates > through - pd.DateOffset(years=years))
    values = np.asarray(panel.values, dtype=float)
    design = _harmonic_design(elapsed_days(dates), harmonics)
    coef = np.full((values.shape[1], design.shape[1]), np.nan)
    for column in range(values.shape[1]):
        valid = mask & np.isfinite(values[:, column])
        if valid.sum() >= design.shape[1]:
            coef[column], *_ = np.linalg.lstsq(design[valid], values[valid, column], rcond=None)
    return coef, design @ coef.T


def _simulate(
    fit: DailyFit,
    history_dates: pd.DatetimeIndex,
    mean: np.ndarray,
    pair: Pair,
    target_year: int,
    cfg: Any,
    seed: np.random.SeedSequence,
    mean_block: int,
) -> np.ndarray:
    """Use the production shared-plan simulator for one 18-series sensitivity run."""
    lead = int(_cfg_value(cfg, "simulate", "site_lead_in_days", 30))
    horizon, accumulate = _horizon(pair, target_year, lead)
    M = int(_cfg_value(cfg, "simulate", "M_site", 10_000))
    candidates = _candidate_days(
        history_dates,
        int(horizon[lead].dayofyear),
        int(_cfg_value(cfg, "simulate", "window_days", 45)),
    )
    valid = np.zeros_like(fit.z, dtype=bool)
    valid[candidates] = np.isfinite(fit.z[candidates])
    plan = joint_block_plan(
        np.random.default_rng(seed), M=M, n_days=len(horizon), mean_block=mean_block, valid_z=valid
    )
    sigma = seasonal_sigma(fit.logvar, horizon.dayofyear.to_numpy())
    fn = daily_hdd if pair.index == "HDD" else daily_cdd
    return simulate_month(
        fit.z,
        plan=plan,
        sigma=sigma,
        ar=fit.ar.coef,
        mean=mean,
        init_state=None,
        series_slice=slice(None),
        accumulate_mask=accumulate,
        index_fn=fn,
    ).T


def run_sensitivities(root: Path, cfg: Any) -> Path:
    """Write ``results/tournament/sensitivities.parquet`` for plan Section 7.7.

    Schema includes ``baseline_label`` plus daily distribution shifts. Each
    perturbation changes just one registered setting from the R2 baseline.
    """
    root = Path(root)
    panel, fips = _subset(root)
    as_of = pd.Timestamp(_cfg_value(cfg, "site", "as_of", "2026-07-01"))
    through = as_of - pd.Timedelta(days=1)
    dates = pd.DatetimeIndex(pd.to_datetime(panel.dates))
    blocks = month_blocks(panel)
    baseline: dict[tuple[str, str], tuple[float, float]] = {}
    rows: list[dict[str, object]] = []
    seed = np.random.SeedSequence(int(getattr(cfg, "seed", 20260901)))
    for spec, child in zip(sensitivity_specs(), seed.spawn(len(sensitivity_specs())), strict=True):
        mean_years = 40 if spec.dimension != "mean_window_years" else spec.value
        mean_months = 480 if mean_years == 40 else (10_000 if mean_years == -1 else mean_years * 12)
        residual_years = 30 if spec.dimension != "residual_window_years" else spec.value
        harmonic = 2 if spec.dimension != "mean_harmonics" else spec.value
        block = 7 if spec.dimension != "mean_block_days" else spec.value
        if harmonic == 2:
            fit = fit_daily(
                panel,
                fit_through=through,
                mean_blocks_stats=blocks,
                mean_months=mean_months,
                residual_years=residual_years,
                ar_orders=tuple(_cfg_value(cfg, "residual", "ar_orders", (1, 2, 3, 5))),
            )

            def mean_for(
                horizon: pd.DatetimeIndex, coefficients: np.ndarray = fit.mean_coef
            ) -> np.ndarray:
                return predict(coefficients, elapsed_days(horizon))
        else:
            coef, full_mean = _harmonic_mean_fit(
                panel, through, mean_years if mean_years > 0 else 75, harmonic
            )
            # Reuse the production residual API after substituting the tested mean.
            residual_panel = SimpleNamespace(
                values=np.asarray(panel.values) - full_mean, dates=panel.dates
            )
            fit = fit_daily(
                residual_panel,
                fit_through=through,
                mean_blocks_stats=month_blocks(residual_panel),
                mean_months=mean_months,
                residual_years=residual_years,
                ar_orders=tuple(_cfg_value(cfg, "residual", "ar_orders", (1, 2, 3, 5))),
            )

            # fit_daily's second mean is intentionally near zero; simulations
            # must add the tested variable-harmonic mean, not that auxiliary fit.
            def mean_for(
                horizon: pd.DatetimeIndex,
                coefficients: np.ndarray = coef,
                count: int = harmonic,
            ) -> np.ndarray:
                return _harmonic_design(elapsed_days(horizon), count) @ coefficients.T

        history_dates = dates[fit.fit_mask]
        for pair, pair_seed in zip(PAIRS, child.spawn(len(PAIRS)), strict=True):
            target = _target_year(as_of, pair)
            lead = int(_cfg_value(cfg, "simulate", "site_lead_in_days", 30))
            horizon, _ = _horizon(pair, target, lead)
            draws = _simulate(
                fit, history_dates, mean_for(horizon), pair, target, cfg, pair_seed, block
            )
            for column, fips_value in enumerate(fips):
                mean_index, sd_index = float(draws[column].mean()), float(draws[column].std(ddof=1))
                key = (pair.key, str(fips_value))
                if spec.dimension == "mean_window_years" and spec.value == 40:
                    baseline[key] = (mean_index, sd_index)
                base_mean, base_sd = baseline.get(key, (np.nan, np.nan))
                rows.append(
                    {
                        "dimension": spec.dimension,
                        "value": spec.value,
                        "variant_label": str(spec.value),
                        "pair": pair.key,
                        "fips": str(fips_value),
                        "mean_index": mean_index,
                        "sd_index": sd_index,
                        "mean_shift_vs_baseline": mean_index - base_mean,
                        "sd_ratio_vs_baseline": sd_index / base_sd if base_sd else np.nan,
                        "M": draws.shape[1],
                        "as_of": as_of.date().isoformat(),
                        "metric": "site_index_distribution",
                        "metric_value": mean_index,
                        "baseline_value": np.nan,
                        "difference_vs_baseline": np.nan,
                        "baseline_label": (
                            "R2 baseline (40y mean / 2 harmonics / 7d block / 30y residual)"
                        ),
                    }
                )
    frame = pd.DataFrame(rows)
    # Baseline is encountered first only for one dimension, so populate all
    # comparison columns after every simulation has been evaluated.
    reference = frame.loc[
        (frame.dimension == "mean_window_years") & (frame.value == 40),
        ["pair", "fips", "mean_index", "sd_index"],
    ]
    reference = reference.rename(columns={"mean_index": "base_mean", "sd_index": "base_sd"})
    frame = frame.drop(columns=["mean_shift_vs_baseline", "sd_ratio_vs_baseline"]).merge(
        reference, on=["pair", "fips"], how="left"
    )
    frame["mean_shift_vs_baseline"] = frame.mean_index - frame.base_mean
    frame["sd_ratio_vs_baseline"] = frame.sd_index / frame.base_sd
    frame = frame.drop(columns=["base_mean", "base_sd"]).sort_values(
        ["dimension", "value", "pair", "fips"], kind="stable"
    )
    output = root / "results" / "tournament" / "sensitivities.parquet"
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output, index=False)
    return output
