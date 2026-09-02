"""Production R2/R2j daily orchestration (plan Sections 7.2--7.4).

The only arrays with a simulation dimension retained here are final contract
draws.  Each call to :func:`simulate_month` handles a chunk of series and
streams its AR state one day at a time.
"""

from __future__ import annotations

import os
import tempfile
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
from weather_basis.models.seasonal_mean import MonthBlocks, elapsed_days, month_blocks, predict
from weather_basis.models.simulate import simulate_month


def _value(cfg: Any, section: str, name: str, default: Any) -> Any:
    group = getattr(cfg, section, None)
    return getattr(group, name, default) if group is not None else default


def _save_npy(path: Path, array: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            np.save(stream, array, allow_pickle=False)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def _save_npz(path: Path, **arrays: np.ndarray) -> Path:
    """Atomically write an unpickled parameter archive."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".npz", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            np.savez(stream, **arrays)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def _combined_panel(root: Path) -> tuple[SimpleNamespace, np.ndarray]:
    """Open county temperatures and any available station temperatures together."""

    directory = Path(root) / "data" / "panel"
    values = np.load(directory / "tavg_f32.npy", mmap_mode="r", allow_pickle=False)
    dates = np.load(directory / "dates.npy", mmap_mode="r", allow_pickle=False)
    fips = np.load(directory / "fips.npy", mmap_mode="r", allow_pickle=False).astype("U")
    labels = fips
    station_path = directory / "stations_tbar_f32.npy"
    station_ids = directory / "station_ids.npy"
    if station_path.exists():
        station = np.load(station_path, mmap_mode="r", allow_pickle=False)
        if station.ndim != 2 or station.shape[0] != values.shape[0]:
            raise ValueError("station temperature panel dimensions are inconsistent")
        if station_ids.exists():
            ids = np.load(station_ids, mmap_mode="r", allow_pickle=False).astype("U")
        else:
            ids = np.asarray([f"station-{i}" for i in range(station.shape[1])], dtype="U")
        if len(ids) != station.shape[1]:
            raise ValueError("station ids do not match station temperature panel")
        values = np.concatenate((values, station), axis=1)
        labels = np.concatenate((labels, ids))
    if values.ndim != 2 or values.shape != (len(dates), len(labels)):
        raise ValueError("daily temperature panel dimensions are inconsistent")
    return SimpleNamespace(values=values, dates=dates, fips=labels), labels


def build_mean_blocks(root: Path, cfg: Any) -> MonthBlocks:
    """Build and persist one set of fixed-basis monthly normal-equation blocks.

    ``mean_blocks.npz`` is intentionally an unpickled collection: the four
    differently shaped sufficient-statistic arrays cannot be represented in a
    single numeric ``.npy`` without an object dtype.
    """

    del cfg  # The fixed basis is a registered D-61 constant, not a fit option.
    root = Path(root)
    panel, _ = _combined_panel(root)
    blocks = month_blocks(panel)
    destination = root / "data" / "panel" / "mean_blocks.npz"
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".mean_blocks.", suffix=".npz", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            np.savez(
                stream,
                gram=blocks.gram,
                xty=blocks.xty,
                yy=blocks.yy,
                counts=blocks.counts,
                months=blocks.months.values.astype("datetime64[D]"),
            )
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return blocks


def _load_or_build_blocks(root: Path, cfg: Any) -> MonthBlocks:
    # Rebuilding from the memory-mapped daily panel is deterministic and avoids
    # accepting a stale sufficient-statistic file after a panel update.
    return build_mean_blocks(root, cfg)


def _target_year(as_of: pd.Timestamp, pair: Pair) -> int:
    """Return the next occurrence strictly after a site valuation date."""

    return as_of.year if pair.month > as_of.month else as_of.year + 1


def _horizon(pair: Pair, target_year: int, lead_days: int) -> tuple[pd.DatetimeIndex, np.ndarray]:
    first = pd.Timestamp(year=target_year, month=pair.month, day=1)
    last = first + pd.offsets.MonthEnd(0)
    dates = pd.date_range(first - pd.Timedelta(days=lead_days), last, freq="D")
    return dates, dates.month.to_numpy() == pair.month


def _candidate_days(
    history_dates: pd.DatetimeIndex, target_doy: int, window_days: int
) -> np.ndarray:
    doy = history_dates.dayofyear.to_numpy()
    distance = np.abs(((doy - target_doy + 182) % 365) - 182)
    return np.flatnonzero(distance <= window_days)


def _fit_site_daily(panel: Any, blocks: MonthBlocks, cfg: Any, through: pd.Timestamp) -> DailyFit:
    return fit_daily(
        panel,
        fit_through=through,
        mean_blocks_stats=blocks,
        mean_months=int(_value(cfg, "mean_model", "window_months", 480)),
        residual_years=int(_value(cfg, "residual", "window_years", 30)),
        ar_orders=tuple(_value(cfg, "residual", "ar_orders", (1, 2, 3, 5))),
        logvar_harmonics=int(_value(cfg, "residual", "logvar_harmonics", 2)),
        logvar_epsilon=float(_value(cfg, "residual", "logvar_eps", 1.0e-6)),
    )


def _subset_blocks(blocks: MonthBlocks, included: np.ndarray) -> MonthBlocks:
    """Select R2j-eligible series without rebuilding the monthly blocks."""

    return MonthBlocks(
        gram=blocks.gram[:, included],
        xty=blocks.xty[:, included],
        yy=blocks.yy[:, included],
        counts=blocks.counts[:, included],
        months=blocks.months,
        basis=blocks.basis,
    )


def _r2j_eligible(panel: Any, n_counties: int, through: pd.Timestamp, cfg: Any) -> np.ndarray:
    """Keep all counties and only stations with the registered minimum history."""

    dates = pd.DatetimeIndex(pd.to_datetime(panel.dates))
    usable = dates <= through
    values = np.asarray(panel.values)[usable]
    min_days = int(_value(cfg, "models", "min_station_years", 25)) * 365
    station_ok = np.isfinite(values[:, n_counties:]).sum(axis=0) >= min_days
    return np.concatenate((np.arange(n_counties), n_counties + np.flatnonzero(station_ok)))


def _daily_calibration(z: np.ndarray, labels: np.ndarray) -> pd.DataFrame:
    """Summarize the site-fit standardized daily innovations per series."""

    rows: list[dict[str, object]] = []
    for column, label in enumerate(labels):
        values = np.asarray(z[:, column], dtype=float)
        values = values[np.isfinite(values)]
        if values.size < 12:
            rows.append(
                {
                    "series": str(label),
                    "n": int(values.size),
                    "skewness": np.nan,
                    "excess_kurtosis": np.nan,
                    "ljung_box_q10": np.nan,
                    "mean_z2": np.nan,
                    "variance_regime_ratio": np.nan,
                    "diagnostic_basis": "unavailable",
                }
            )
            continue
        centered = values - values.mean()
        m2 = float(np.mean(centered * centered))
        skew = float(np.mean(centered**3) / m2**1.5) if m2 > 0 else np.nan
        kurt = float(np.mean(centered**4) / m2**2 - 3.0) if m2 > 0 else np.nan
        ac = []
        for lag in range(1, 11):
            left, right = centered[lag:], centered[:-lag]
            ac.append(
                float(np.corrcoef(left, right)[0, 1])
                if np.std(left) > 0 and np.std(right) > 0
                else 0.0
            )
        q10 = float(
            values.size
            * (values.size + 2)
            * sum(rho * rho / (values.size - lag) for lag, rho in enumerate(ac, 1))
        )
        width = max(1, values.size // 3)
        early, late = values[:width], values[-width:]
        early_var = float(np.var(early))
        rows.append(
            {
                "series": str(label),
                "n": int(values.size),
                "skewness": skew,
                "excess_kurtosis": kurt,
                "ljung_box_q10": q10,
                "mean_z2": float(np.mean(values * values)),
                "variance_regime_ratio": float(np.var(late) / early_var)
                if early_var > 0
                else np.nan,
                "diagnostic_basis": "daily_R2_standardized_innovation",
            }
        )
    return pd.DataFrame(rows)


def _simulate_pair(
    fit: DailyFit,
    history_dates: pd.DatetimeIndex,
    pair: Pair,
    target_year: int,
    cfg: Any,
    seed: np.random.SeedSequence,
) -> np.ndarray:
    lead = int(_value(cfg, "simulate", "site_lead_in_days", 30))
    horizon, accumulate = _horizon(pair, target_year, lead)
    M = int(_value(cfg, "simulate", "M_site", 10_000))
    candidate = _candidate_days(
        history_dates,
        int(horizon[lead].dayofyear),
        int(_value(cfg, "simulate", "window_days", 45)),
    )
    # The R2j candidate pool is a complete-case intersection across every
    # included county and station, then restricted to the seasonal window.
    valid_z = np.zeros_like(fit.z, dtype=bool)
    valid_z[candidate] = np.isfinite(fit.z[candidate])
    plan = joint_block_plan(
        np.random.default_rng(seed),
        M=M,
        n_days=len(horizon),
        mean_block=float(_value(cfg, "simulate", "mean_block", 7)),
        valid_z=valid_z,
    )
    t = elapsed_days(horizon)
    mean = predict(fit.mean_coef, t)
    sigma = seasonal_sigma(fit.logvar, horizon.dayofyear.to_numpy())
    output = np.empty((fit.mean_coef.shape[0], M), dtype=np.float32)
    chunk = int(_value(cfg, "simulate", "chunk_series", 200))
    if chunk < 1:
        raise ValueError("simulate.chunk_series must be positive")
    index_fn = daily_hdd if pair.index == "HDD" else daily_cdd
    for start in range(0, output.shape[0], chunk):
        stop = min(start + chunk, output.shape[0])
        # This is the critical bounded call: only (M, days-in-state, chunk)
        # working arrays exist within simulate_month, never a path cube.
        output[start:stop] = simulate_month(
            fit.z,
            plan=plan,
            sigma=sigma,
            ar=fit.ar.coef,
            mean=mean,
            init_state=None,
            series_slice=slice(start, stop),
            accumulate_mask=accumulate,
            index_fn=index_fn,
        ).T
    return output


def run_site_daily(root: Path, cfg: Any) -> dict[str, Path]:
    """Fit R2 once and write deterministic aligned/sorted R2j site draws.

    The fit date is the site as-of date minus one day.  Each pair gets a child
    SeedSequence and one shared plan, so samples in every output row represent
    the same national weather scenario.
    """

    root = Path(root)
    panel, labels = _combined_panel(root)
    full_values, full_dates, full_labels = panel.values, panel.dates, labels.copy()
    n_counties = len(np.load(root / "data" / "panel" / "fips.npy", mmap_mode="r"))
    as_of = pd.Timestamp(_value(cfg, "site", "as_of", "2026-07-01"))
    through = as_of - pd.Timedelta(days=1)
    blocks = _load_or_build_blocks(root, cfg)
    included = _r2j_eligible(panel, n_counties, through, cfg)
    panel = SimpleNamespace(values=np.asarray(panel.values)[:, included], dates=panel.dates)
    labels = labels[included]
    blocks = _subset_blocks(blocks, included)
    fit = _fit_site_daily(panel, blocks, cfg, through)
    history_dates = pd.DatetimeIndex(pd.to_datetime(panel.dates))[fit.fit_mask]
    seed = np.random.SeedSequence(int(getattr(cfg, "seed", 20260901)))
    aligned_dir = root / "results" / "draws" / "R2j_aligned"
    sorted_dir = root / "results" / "draws" / "R2j"
    params = root / "results" / "models" / "params"
    for pair, child in zip(PAIRS, seed.spawn(len(PAIRS)), strict=True):
        target = _target_year(as_of, pair)
        draws = _simulate_pair(fit, history_dates, pair, target, cfg, child)
        _save_npy(aligned_dir / f"{pair.key}_site.npy", draws)
        _save_npy(sorted_dir / f"{pair.key}_site.npy", np.sort(draws, axis=1))
        _save_npy(params / f"mean_{pair.key}_site.npy", fit.mean_coef)
        _save_npz(
            params / f"ar_{pair.key}_site.npz",
            coef=fit.ar.coef,
            order=fit.ar.order,
            bic=fit.ar.bic,
        )
    _save_npy(sorted_dir / "series_labels.npy", labels)
    # The registered calibration table covers counties plus the 13 listed CME
    # stations; the five Nebraska stations remain available to the joint check.
    calibration = _daily_calibration(fit.z[:, : n_counties + 13], labels[: n_counties + 13])
    calibration_path = root / "results/tournament/calibration.parquet"
    calibration_path.parent.mkdir(parents=True, exist_ok=True)
    calibration.sort_values("series", kind="stable").to_parquet(calibration_path, index=False)

    from weather_basis.models.run import _joint_check_from_site_draws

    joint_path = _joint_check_from_site_draws(
        root, np.asarray(full_values), np.asarray(full_dates), full_labels, cfg
    )
    result = {
        "draws": sorted_dir,
        "aligned": aligned_dir,
        "params": params,
        "calibration": calibration_path,
    }
    if joint_path is not None:
        result["joint_check"] = joint_path
    return result
