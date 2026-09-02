"""Deterministic file orchestration for the Section 7 model tournament.

The runner deliberately keeps the large objects on disk.  At no point does it
construct a draws-by-days-by-series cube: a pair/origin is emitted as one
``(series, M)`` matrix and its score rows are written before moving on.
"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import sys
import tempfile
from calendar import monthrange
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import gammaln

from weather_basis.contracts.calendar import PAIRS, Pair

from .residual import seasonal_sigma
from .run_daily import _fit_site_daily, _load_or_build_blocks, _subset_blocks
from .scoring import brier, coverage, crps_from_samples, pit
from .seasonal_mean import elapsed_days, predict
from .tournament import tournament_selection


def _county_count(root: Path) -> int:
    """Return the fixed county slice; station rows never enter unit scores."""
    return int(
        np.load(root / "data" / "panel" / "fips.npy", mmap_mode="r", allow_pickle=False).size
    )


def _calibration_rows(history: np.ndarray, seasons: np.ndarray, labels: np.ndarray) -> pd.DataFrame:
    """Compute observed, index-level innovation diagnostics without inventing values.

    The full daily R2 fit emits the same fields from standardized daily
    innovations.  This runner deliberately labels its cheaper annual fallback
    so a model card can never mistake it for the daily diagnostic.
    """
    rows: list[dict[str, object]] = []
    for column, label in enumerate(labels):
        y = np.asarray(history[:, column], dtype=float)
        valid = np.isfinite(y)
        yy, tt = y[valid], np.asarray(seasons, dtype=float)[valid]
        if yy.size < 6:
            rows.append(
                {
                    "series": str(label),
                    "n": int(yy.size),
                    "skewness": np.nan,
                    "excess_kurtosis": np.nan,
                    "ljung_box_q10": np.nan,
                    "mean_z2": np.nan,
                    "variance_regime_ratio": np.nan,
                    "diagnostic_basis": "unavailable",
                }
            )
            continue
        beta = np.polyfit(tt, yy, 1)
        residual = yy - np.polyval(beta, tt)
        scale = float(np.sqrt(np.mean(residual**2)))
        z = residual / scale if scale > 0 else np.full_like(residual, np.nan)
        finite = z[np.isfinite(z)]
        if finite.size < 3:
            skew = kurt = q10 = z2 = ratio = np.nan
        else:
            centred = finite - finite.mean()
            m2 = float(np.mean(centred**2))
            skew = float(np.mean(centred**3) / m2**1.5) if m2 > 0 else np.nan
            kurt = float(np.mean(centred**4) / m2**2 - 3) if m2 > 0 else np.nan
            ac = [
                float(np.corrcoef(centred[k:], centred[:-k])[0, 1])
                if finite.size > k + 1 and np.std(centred[k:]) > 0 and np.std(centred[:-k]) > 0
                else 0.0
                for k in range(1, min(10, finite.size - 1) + 1)
            ]
            q10 = float(
                finite.size
                * (finite.size + 2)
                * sum(a * a / (finite.size - k) for k, a in enumerate(ac, start=1))
            )
            z2 = float(np.mean(finite**2))
            first, last = finite[: max(1, finite.size // 3)], finite[-max(1, finite.size // 3) :]
            ratio = float(np.var(last) / np.var(first)) if np.var(first) > 0 else np.nan
        rows.append(
            {
                "series": str(label),
                "n": int(yy.size),
                "skewness": skew,
                "excess_kurtosis": kurt,
                "ljung_box_q10": q10,
                "mean_z2": z2,
                "variance_regime_ratio": ratio,
                "diagnostic_basis": "annual_index_residual_fallback",
            }
        )
    return pd.DataFrame(rows)


def _power_statement(score_data: pd.DataFrame, n_origins: int, seed: int) -> dict[str, object]:
    """Daily-R2 score-resampling power calculation under a centered null.

    This retains the observed heteroskedasticity of the fitted daily R2
    tournament rather than imposing a unit-variance normal approximation.
    It resamples origin-level paired R2/R1 skills after centering within the
    registered (pair, state) unit, which is the equal-skill null.
    """

    n = max(int(n_origins), 2)
    table = score_data.pivot_table(
        index=["pair", "state", "origin"], columns="rung", values="crps", aggfunc="sum"
    )
    if not {"R1", "R2"}.issubset(table.columns):
        raise ValueError("daily R2 power requires paired R1/R2 score rows")
    ratio = 1.0 - table["R2"] / table["R1"]
    centered = ratio - ratio.groupby(level=[0, 1]).transform("mean")
    innovations = centered[np.isfinite(centered)].to_numpy(dtype=float)
    if innovations.size < n:
        raise ValueError("insufficient paired daily-R2 origin scores for power calculation")
    rng = np.random.default_rng(np.random.SeedSequence(seed).spawn(1)[0])
    null = rng.choice(innovations, size=(80_000, n), replace=True).mean(axis=1)
    critical = float(np.quantile(null, 0.90))
    grid = np.linspace(0.0, 2.0, 2_001)
    # Under an additive equal-variance skill alternative, shifting the
    # simulated null means is the same experiment as redrawing all origins;
    # it avoids a 2,001-times larger Monte Carlo allocation.
    power = np.array([(null + d > critical).mean() for d in grid])
    return {
        "n_origins": n,
        "power": 0.80,
        "alpha_one_sided": 0.10,
        "minimum_detectable_skill_80": float(grid[np.flatnonzero(power >= 0.80)[0]]),
        "method": (
            "Monte Carlo origin bootstrap of centered fitted-daily-R2 paired CRPS skills "
            "under equal-skill null"
        ),
        "seed": seed,
    }


def _value(cfg: Any, section: str, name: str, default: Any) -> Any:
    group = getattr(cfg, section, None)
    return getattr(group, name, default) if group is not None else default


def _load_panel(root: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    panel = root / "data" / "panel"
    values = np.load(panel / "tavg_f32.npy", mmap_mode="r", allow_pickle=False)
    dates = np.load(panel / "dates.npy", mmap_mode="r", allow_pickle=False)
    fips = np.load(panel / "fips.npy", mmap_mode="r", allow_pickle=False).astype("U5")
    if values.ndim != 2 or values.shape != (dates.size, fips.size):
        raise ValueError("county panel dimensions are inconsistent")
    station_file = panel / "stations_tbar_f32.npy"
    ids_file = panel / "station_ids.npy"
    if station_file.exists() and ids_file.exists():
        station = np.load(station_file, mmap_mode="r", allow_pickle=False)
        ids = np.load(ids_file, mmap_mode="r", allow_pickle=False).astype("U")
        if station.ndim != 2 or station.shape[0] != dates.size or station.shape[1] != ids.size:
            raise ValueError("station panel dimensions are inconsistent")
        values = np.concatenate((values, station), axis=1)
        labels = np.concatenate((fips.astype("U32"), ids.astype("U32")))
    else:
        labels = fips
    return np.asarray(values), np.asarray(dates), labels


def _load_county_panel(root: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Open the county panel without materializing the station columns.

    Rolling score units are counties only.  Avoiding the county/station
    concatenate here keeps the master fit's RSS below the single-process cap.
    """

    directory = Path(root) / "data" / "panel"
    values = np.load(directory / "tavg_f32.npy", mmap_mode="r", allow_pickle=False)
    dates = np.load(directory / "dates.npy", mmap_mode="r", allow_pickle=False)
    fips = np.load(directory / "fips.npy", mmap_mode="r", allow_pickle=False).astype("U5")
    if values.shape != (dates.size, fips.size):
        raise ValueError("county panel dimensions are inconsistent")
    return values, dates, fips


def _pair_history(
    values: np.ndarray, dates: np.ndarray, pair: Pair
) -> tuple[np.ndarray, np.ndarray]:
    days = dates.astype("datetime64[D]")
    months = days.astype("datetime64[M]")
    years = months.astype("datetime64[Y]").astype(int) + 1970
    month_number = months.astype(int) % 12 + 1
    seasons = np.unique(years[month_number == pair.month])
    daily = (
        np.maximum(65.0 - values, 0.0) if pair.index == "HDD" else np.maximum(values - 65.0, 0.0)
    )
    output = np.full((seasons.size, values.shape[1]), np.nan, dtype=np.float64)
    for row, season in enumerate(seasons):
        selected = (years == season) & (month_number == pair.month)
        block = daily[selected]
        complete = block.shape[0] == monthrange(int(season), pair.month)[1]
        complete = complete & np.isfinite(block).all(axis=0)
        output[row, complete] = block[:, complete].sum(axis=0)
    return seasons, output


def _save_npy(path: Path, values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            np.save(stream, values, allow_pickle=False)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def _save_npz(path: Path, **arrays: np.ndarray) -> None:
    """Atomically write compact parameter archives without pickle data."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".npz", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            np.savez(stream, **arrays)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def _write_frame(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.sort_values(list(frame.columns), kind="stable", na_position="last").to_parquet(
        path, index=False
    )


def _index_comparator_draws(
    history: np.ndarray,
    seasons: np.ndarray,
    origin: int,
    M: int,
    seed: np.random.SeedSequence,
    cfg: Any,
) -> dict[str, np.ndarray]:
    """Build vectorized index-level R0/R1 comparator samples for one origin.

    The county panel has complete annual contract-month histories.  Taking
    advantage of that invariant turns the former 3,107 independent Python
    optimizations into one masked matrix likelihood calculation.  R1 still
    maximizes the Student-t profile likelihood (scale and df jointly).  R2 is
    deliberately absent here: the production runner constructs it directly
    from daily temperatures.  The single origin
    generator is intentionally deterministic and scoped by the registered
    pair/origin SeedSequence child.
    """
    stop = int(np.searchsorted(seasons, origin))
    n = history.shape[1]
    r0 = np.full((n, M), np.nan, dtype=np.float32)
    r1 = np.full_like(r0, np.nan)
    window = int(_value(cfg, "r1", "window_years", 40))
    train = np.asarray(history[max(0, stop - window) : stop], dtype=float)
    time = np.asarray(seasons[max(0, stop - window) : stop], dtype=float)
    valid = np.isfinite(train)
    counts = valid.sum(axis=0)
    eligible = counts >= 3
    if not np.any(eligible):
        return {"R0": r0, "R1": r1}
    # Closed-form masked OLS for every county.  The production panel is
    # complete, while the mask preserves fixture/partial-history behaviour.
    x = time[:, None]
    y = np.where(valid, train, 0.0)
    sx, sy = (valid * x).sum(axis=0), y.sum(axis=0)
    sxx, sxy = (valid * x * x).sum(axis=0), (x * y).sum(axis=0)
    denominator = counts * sxx - sx * sx
    eligible &= np.abs(denominator) > np.finfo(float).eps
    slope = np.divide(counts * sxy - sx * sy, denominator, out=np.zeros(n), where=eligible)
    intercept = np.divide(sy - slope * sx, counts, out=np.zeros(n), where=eligible)
    fitted = intercept[None, :] + x * slope[None, :]
    residual = np.where(valid, train - fitted, np.nan)
    rng = np.random.default_rng(seed)
    burn = np.asarray(history[max(0, stop - 30) : stop], dtype=float).T
    burn_ok = np.isfinite(burn).all(axis=1) & eligible
    choices = rng.integers(0, burn.shape[1], size=(n, M))
    r0[burn_ok] = np.take_along_axis(burn[burn_ok], choices[burn_ok], axis=1).astype(np.float32)

    # Profile the Student-t likelihood.  For each proposed df, the scale MLE
    # solves the usual EM/fixed-point equation; all counties are solved in
    # parallel.  A 0.5-df grid followed by a local quadratic refinement is
    # materially more accurate than a coarse moment approximation and avoids
    # 1.4 million scipy optimizer calls in the rolling production run.
    floor = float(_value(cfg, "r1", "nu_floor", 4))
    ceiling = float(_value(cfg, "r1", "nu_ceiling", 100))
    nus = np.arange(floor, ceiling + 0.25, 0.5, dtype=float)
    squared = np.where(valid, residual * residual, 0.0)
    scale0 = np.sqrt(np.divide(squared.sum(axis=0), counts, out=np.ones(n), where=eligible))
    scale0 = np.maximum(scale0, np.finfo(float).eps)
    likelihood = np.full((nus.size, n), -np.inf)
    scales = np.empty((nus.size, n), dtype=float)
    for row, nu in enumerate(nus):
        scale2 = scale0 * scale0
        for _ in range(10):
            weight = (nu + 1.0) / (nu + squared / scale2[None, :])
            scale2 = np.divide(
                (weight * squared * valid).sum(axis=0), counts, out=scale2, where=eligible
            )
            scale2 = np.maximum(scale2, np.finfo(float).eps)
        scales[row] = np.sqrt(scale2)
        u2 = squared / scale2[None, :]
        logpdf = (
            gammaln((nu + 1.0) / 2.0)
            - gammaln(nu / 2.0)
            - 0.5 * np.log(np.pi * nu)
            - np.log(scales[row])[None, :]
            - ((nu + 1.0) / 2.0) * np.log1p(u2 / nu)
        )
        likelihood[row] = np.where(eligible, (logpdf * valid).sum(axis=0), -np.inf)
    best = np.argmax(likelihood, axis=0)
    nu = nus[best]
    scale = scales[best, np.arange(n)]
    # A local parabolic interpolation of the profiled log likelihood removes
    # most grid quantization without sacrificing vectorized runtime.
    interior = (best > 0) & (best < nus.size - 1) & eligible
    if np.any(interior):
        lo, mid, hi = (
            likelihood[best[interior] - 1, np.flatnonzero(interior)],
            likelihood[best[interior], np.flatnonzero(interior)],
            likelihood[best[interior] + 1, np.flatnonzero(interior)],
        )
        delta = np.clip(
            0.5 * (lo - hi) / np.maximum(lo - 2 * mid + hi, -np.finfo(float).eps), -0.5, 0.5
        )
        nu[interior] = np.clip(nu[interior] + 0.5 * delta, floor, ceiling)
    location = intercept + slope * float(origin)
    r1[eligible] = np.maximum(
        location[eligible, None]
        + scale[eligible, None] * rng.standard_t(nu[eligible, None], size=(int(eligible.sum()), M)),
        0.0,
    ).astype(np.float32)
    return {"R0": r0, "R1": r1}


def _score_rows(
    draws: dict[str, np.ndarray],
    outcome: np.ndarray,
    labels: np.ndarray,
    pair: Pair,
    origin: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for rung, matrix in draws.items():
        for column, y in enumerate(outcome):
            sample = matrix[column]
            if not np.isfinite(y) or not np.isfinite(sample).all():
                continue
            # The two registered Brier strikes are the historical mean and one
            # historical standard deviation above it; their values are useful
            # diagnostics without coupling score rows to option pricing.
            strike0 = float(np.mean(sample))
            strike1 = strike0 + float(np.std(sample))
            rows.append(
                {
                    "pair": pair.key,
                    "fips": str(labels[column]),
                    "state": str(labels[column])[:2],
                    "origin": origin,
                    "rung": rung,
                    "crps": crps_from_samples(sample, float(y)),
                    "pit": pit(sample, float(y)),
                    "coverage50": coverage(sample, float(y), 0.50),
                    "coverage80": coverage(sample, float(y), 0.80),
                    "coverage95": coverage(sample, float(y), 0.95),
                    "brier_z0": brier(sample, float(y), strike0),
                    "brier_z1": brier(sample, float(y), strike1),
                }
            )
    return rows


def _score_frame(
    draws: dict[str, np.ndarray], outcome: np.ndarray, labels: np.ndarray, pair: Pair, origin: int
) -> pd.DataFrame:
    """Vectorized Section 7.5 scoring for all counties in one origin/rung.

    Sorting is performed once per row and all CRPS/PIT/coverage/Brier columns
    are then matrix reductions.  This replaces the former 4.2 million Python
    row loops without changing the empirical-score definition.
    """
    y = np.asarray(outcome, dtype=float)
    labels = np.asarray(labels).astype("U5")
    frames: list[pd.DataFrame] = []
    for rung, matrix in draws.items():
        sample = np.asarray(matrix, dtype=float)
        good = np.isfinite(y) & np.isfinite(sample).all(axis=1)
        if not np.any(good):
            continue
        x = np.sort(sample[good], axis=1)
        yy = y[good]
        m = x.shape[1]
        weight = (2.0 * np.arange(1, m + 1) - m - 1.0) / (m * m)
        crps = np.mean(np.abs(x - yy[:, None]), axis=1) - x @ weight
        means = x.mean(axis=1)
        stds = x.std(axis=1)
        p = np.mean(x <= yy[:, None], axis=1)
        quantiles = np.quantile(x, [0.025, 0.10, 0.25, 0.75, 0.90, 0.975], axis=1)
        coverage50 = (quantiles[2] <= yy) & (yy <= quantiles[3])
        coverage80 = (quantiles[1] <= yy) & (yy <= quantiles[4])
        coverage95 = (quantiles[0] <= yy) & (yy <= quantiles[5])
        brier0 = (np.mean(x > means[:, None], axis=1) - (yy > means)) ** 2
        strike1 = means + stds
        brier1 = (np.mean(x > strike1[:, None], axis=1) - (yy > strike1)) ** 2
        good_labels = labels[good]
        frames.append(
            pd.DataFrame(
                {
                    "pair": pair.key,
                    "fips": good_labels,
                    "state": good_labels.astype("U2"),
                    "origin": origin,
                    "rung": rung,
                    "crps": crps,
                    "pit": p,
                    "coverage50": coverage50,
                    "coverage80": coverage80,
                    "coverage95": coverage95,
                    "brier_z0": brier0,
                    "brier_z1": brier1,
                }
            )
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _manifest(root: Path, cfg: Any, stage: str, outputs: list[Path], *, unlocked: bool) -> None:
    digest: dict[str, str] = {}
    for path in outputs:
        if path.is_file():
            digest[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    payload = {
        "stage": stage,
        "created_utc": datetime.now(UTC).isoformat(),
        "seed": int(getattr(cfg, "seed", 20260901)),
        "holdout_unlocked": unlocked,
        "paths_out": sorted(digest),
        "sha256_out": digest,
    }
    path = root / "results" / "manifests" / f"{stage}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _tournament_dates(
    pair: Pair, origin: int
) -> tuple[pd.Timestamp, pd.Timestamp, pd.DatetimeIndex, np.ndarray]:
    """Registered origin convention: value one month before settlement month.

    The daily fit ends on the last day two months before the contract month;
    simulation begins on the next observed calendar day and only accumulates
    degree days in the contract month.
    """

    target = pd.Timestamp(year=int(origin), month=int(pair.month), day=1)
    as_of = target - pd.DateOffset(months=1)
    through = as_of - pd.Timedelta(days=1)
    horizon = pd.date_range(
        through + pd.Timedelta(days=1), target + pd.offsets.MonthEnd(0), freq="D"
    )
    return as_of, through, horizon, horizon.month.to_numpy() == pair.month


def _stationary_plan_indices(
    rng: np.random.Generator, *, M: int, n_days: int, candidates: np.ndarray, mean_block: float
) -> np.ndarray:
    """Vectorized stationary-bootstrap plan for one marginal series.

    This is algebraically the geometric-block construction: each day begins a
    fresh block with probability ``1 / mean_block`` and otherwise advances one
    calendar day within the candidate window.  It avoids Python loops over
    paths while retaining a dedicated RNG stream for each county.
    """

    choices = np.asarray(candidates, dtype=np.int32)
    if not choices.size:
        raise ValueError("daily R2 simulation has no candidate innovation days")
    if mean_block <= 0:
        raise ValueError("simulate.mean_block must be positive")
    p = 1.0 / float(mean_block)
    restart = rng.random((M, n_days)) < p
    restart[:, 0] = True
    starts = rng.integers(0, choices.size, size=(M, n_days), dtype=np.int32)
    positions = np.empty((M, n_days), dtype=np.int32)
    positions[:, 0] = starts[:, 0]
    for day in range(1, n_days):
        positions[:, day] = np.where(
            restart[:, day], starts[:, day], (positions[:, day - 1] + 1) % choices.size
        )
    return choices[positions]


def _daily_r2_draws(
    panel: np.ndarray,
    dates: np.ndarray,
    blocks: Any,
    pair: Pair,
    origin: int,
    M: int,
    cfg: Any,
    seed: np.random.SeedSequence,
) -> tuple[np.ndarray, Any]:
    """Fit and simulate the registered daily R2 model for one pair/origin.

    Counties receive independent ``SeedSequence`` children.  Work is bounded
    by a county chunk: plans are ``(chunk, M, horizon)`` and the day loop keeps
    only AR state and the monthly accumulator, never a path cube.
    """

    _, through, horizon, accumulate = _tournament_dates(pair, origin)
    daily_panel = type("Panel", (), {"values": panel, "dates": dates})()
    fit = _fit_site_daily(daily_panel, blocks, cfg, through)
    history_dates = pd.DatetimeIndex(pd.to_datetime(dates))[fit.fit_mask]
    target_day = int(pd.Timestamp(year=origin, month=pair.month, day=1).dayofyear)
    doy = history_dates.dayofyear.to_numpy()
    distance = np.abs(((doy - target_day + 182) % 365) - 182)
    candidates = np.flatnonzero(distance <= int(_value(cfg, "simulate", "window_days", 45)))
    valid = np.isfinite(fit.z)
    if not np.all(valid[candidates]):
        # County panels are complete, but keeping this check makes partial
        # fixture inputs fail loudly rather than silently mixing candidate sets.
        candidates = candidates[np.all(valid[candidates], axis=1)]
    if not candidates.size:
        raise ValueError(f"no complete daily innovation candidates for {pair.key} {origin}")

    future_t = elapsed_days(horizon)
    mean = predict(fit.mean_coef, future_t)
    sigma = seasonal_sigma(fit.logvar, horizon.dayofyear.to_numpy())
    values = np.asarray(panel, dtype=np.float64)
    fit_values = values[fit.fit_mask]
    fitted_history = predict(fit.mean_coef, elapsed_days(history_dates))
    residual_history = fit_values - fitted_history
    n_series = values.shape[1]
    output = np.empty((n_series, M), dtype=np.float32)
    chunk = int(_value(cfg, "simulate", "chunk_series", 200))
    if chunk < 1:
        raise ValueError("simulate.chunk_series must be positive")
    children = seed.spawn(n_series)
    index_is_hdd = pair.index == "HDD"
    max_p = fit.ar.coef.shape[1]
    for start in range(0, n_series, chunk):
        stop = min(start + chunk, n_series)
        width = stop - start
        plans = np.stack(
            [
                _stationary_plan_indices(
                    np.random.default_rng(child),
                    M=M,
                    n_days=len(horizon),
                    candidates=candidates,
                    mean_block=float(_value(cfg, "simulate", "mean_block", 7)),
                )
                for child in children[start:stop]
            ],
            axis=0,
        )
        state = np.zeros((max_p, M, width), dtype=np.float64)
        for lag in range(max_p):
            row = residual_history[-1 - lag, start:stop]
            state[lag] = np.where(np.isfinite(row), row, 0.0)[None, :]
        total = np.zeros((M, width), dtype=np.float64)
        coef = fit.ar.coef[start:stop]
        columns = np.arange(start, stop)
        for day in range(len(horizon)):
            source = plans[:, :, day].T
            innovation = fit.z[source, columns[None, :]] * sigma[day, start:stop][None, :]
            residual = innovation + np.einsum("pmc,cp->mc", state, coef, optimize=True)
            if max_p:
                state[1:] = state[:-1]
                state[0] = residual
            if accumulate[day]:
                temperature = mean[day, start:stop][None, :] + residual
                increment = (
                    np.maximum(65.0 - temperature, 0.0)
                    if index_is_hdd
                    else np.maximum(temperature - 65.0, 0.0)
                )
                total += increment
        output[start:stop] = total.T.astype(np.float32)
    return output, fit


def _daily_calibration_by_origin(
    fit: Any, labels: np.ndarray, pair: Pair, origin: int
) -> pd.DataFrame:
    """The same daily-standardized diagnostic fields, summarized at an origin."""

    z = np.asarray(fit.z, dtype=float)
    rows: list[dict[str, object]] = []
    for column, label in enumerate(labels):
        values = z[:, column]
        values = values[np.isfinite(values)]
        if values.size < 12:
            continue
        centered = values - values.mean()
        m2 = float(np.mean(centered * centered))
        ac = [
            float(np.corrcoef(centered[k:], centered[:-k])[0, 1])
            if np.std(centered[k:]) > 0 and np.std(centered[:-k]) > 0
            else 0.0
            for k in range(1, 11)
        ]
        width = max(1, values.size // 3)
        early = float(np.var(values[:width]))
        rows.append(
            {
                "pair": pair.key,
                "origin": int(origin),
                "series": str(label),
                "skewness": float(np.mean(centered**3) / m2**1.5) if m2 > 0 else np.nan,
                "excess_kurtosis": float(np.mean(centered**4) / m2**2 - 3.0) if m2 > 0 else np.nan,
                "ljung_box_q10": float(
                    values.size
                    * (values.size + 2)
                    * sum(r * r / (values.size - i) for i, r in enumerate(ac, 1))
                ),
                "mean_z2": float(np.mean(values * values)),
                "variance_regime_ratio": (
                    float(np.var(values[-width:]) / early) if early > 0 else np.nan
                ),
                "diagnostic_basis": "daily_R2_standardized_innovation",
            }
        )
    return pd.DataFrame(rows)


def _r0_draws_from_anomalies(
    root: Path,
    pair: Pair,
    origin: int,
    labels: np.ndarray,
    M: int,
    seed: np.random.SeedSequence,
    fallback_history: np.ndarray,
    seasons: np.ndarray,
) -> np.ndarray:
    """R0: target trailing normal plus a sampled trailing-30 anomaly.

    The fixture runner intentionally has no index parquet.  That narrow test
    path falls back to its supplied history; production has to use the frozen
    index-normal/anomaly table and fails if it is malformed.
    """

    path = Path(root) / "results" / "indices" / f"county_{pair.key}.parquet"
    if not path.exists():
        normal = np.nanmean(fallback_history[-30:], axis=0)
        anomaly = fallback_history[-30:] - normal[None, :]
    else:
        table = pd.read_parquet(path, columns=["fips", "season", "normal", "anomaly"])
        table["fips"] = table["fips"].astype(str).str.zfill(5)
        table = table.loc[table["fips"].isin(labels) & (table["season"] <= int(origin))]
        normal_frame = table.loc[table["season"].eq(int(origin))].set_index("fips")["normal"]
        normals = normal_frame.reindex(labels)
        if normals.isna().any():
            raise ValueError(f"R0 missing target normal for {pair.key} {origin}")
        normal = normals.to_numpy(dtype=float)
        prior = table.loc[table["season"].lt(int(origin)) & table["season"].ge(int(origin) - 30)]
        anomaly = (
            prior.pivot(index="season", columns="fips", values="anomaly")
            .reindex(columns=labels)
            .to_numpy(dtype=float)
        )
    out = np.full((len(labels), M), np.nan, dtype=np.float32)
    for column, child in enumerate(seed.spawn(len(labels))):
        pool = anomaly[:, column]
        pool = pool[np.isfinite(pool)]
        if pool.size:
            out[column] = np.maximum(
                float(normal[column])
                + np.random.default_rng(child).choice(pool, size=M, replace=True),
                0.0,
            ).astype(np.float32)
    return out


def _joint_check_from_site_draws(
    root: Path, values: np.ndarray, dates: np.ndarray, labels: np.ndarray, cfg: Any
) -> Path | None:
    """Score aligned R2j hedges against independently paired R2 marginals.

    The independent comparator is a deterministic permutation of the station
    marginal paths.  It preserves each modelled marginal exactly and removes
    path alignment, which is precisely the zero-correlation comparator in
    Section 7.6.  A failed row is retained as evidence rather than rounded or
    overwritten: it is a joint-plan diagnostic, not a selection statistic.
    """
    atlas_path = root / "results" / "atlas" / "pairs.parquet"
    registry_path = root / "data" / "metadata" / "station_registry.csv"
    counties_path = root / "data" / "contracts" / "station_county.csv"
    aligned_dir = root / "results" / "draws" / "R2j_aligned"
    if not (
        atlas_path.exists()
        and registry_path.exists()
        and counties_path.exists()
        and aligned_dir.exists()
    ):
        return None
    n_counties = _county_count(root)
    registry = pd.read_csv(registry_path, dtype={"ghcnd_id": str})
    county = pd.read_csv(counties_path, dtype={"ghcnd_id": str, "county_fips": str})
    checks = registry.merge(county[["ghcnd_id", "county_fips"]], on="ghcnd_id", how="inner")
    if checks.empty:
        return None
    index_by_label = {str(label): i for i, label in enumerate(labels)}
    fips_by_label = {str(label): i for i, label in enumerate(labels[:n_counties])}
    atlas = pd.read_parquet(atlas_path, columns=["pair", "fips", "station_pit", "h_pit"])
    rows: list[dict[str, object]] = []
    seed = np.random.SeedSequence(int(getattr(cfg, "seed", 20260901))).spawn(len(PAIRS))
    for pair, child in zip(PAIRS, seed, strict=True):
        path = aligned_dir / f"{pair.key}_site.npy"
        if not path.exists():
            continue
        aligned = np.load(path, mmap_mode="r", allow_pickle=False)
        seasons, history = _pair_history(values, dates, pair)
        outcome_at = int(np.searchsorted(seasons, 2025))
        if outcome_at >= seasons.size or seasons[outcome_at] != 2025:
            continue
        pair_atlas = atlas.loc[atlas["pair"].eq(pair.key)].set_index("fips")
        rng = np.random.default_rng(child)
        for item in checks.itertuples(index=False):
            county_label, station_label = str(item.county_fips).zfill(5), str(item.ghcnd_id)
            ci, si = fips_by_label.get(county_label), index_by_label.get(station_label)
            if ci is None or si is None or county_label not in pair_atlas.index:
                continue
            y_c, y_s = history[outcome_at, ci], history[outcome_at, si]
            # Fit the diagnostic hedge on only pre-confirmation observations.
            # It is intentionally station-specific: several Nebraska rows are
            # not the atlas's selected CME proxy and therefore have no h_pit.
            train_c, train_s = history[:outcome_at, ci], history[:outcome_at, si]
            train = np.isfinite(train_c) & np.isfinite(train_s)
            if np.count_nonzero(train) < 10:
                continue
            centered_c = train_c[train] - np.mean(train_c[train])
            centered_s = train_s[train] - np.mean(train_s[train])
            variance = float(centered_s @ centered_s)
            if variance == 0:
                continue
            h = float((centered_c @ centered_s) / variance)
            county_draw, station_draw = (
                np.asarray(aligned[ci], dtype=float),
                np.asarray(aligned[si], dtype=float),
            )
            good = np.isfinite(county_draw) & np.isfinite(station_draw)
            if not (np.isfinite(y_c) and np.isfinite(y_s) and np.count_nonzero(good) >= 4):
                continue
            joint = np.sort(county_draw[good] - h * station_draw[good])
            independent = np.sort(
                county_draw[good] - h * station_draw[good][rng.permutation(np.count_nonzero(good))]
            )
            realized = float(y_c - h * y_s)
            r2j = crps_from_samples(joint, realized)
            ind = crps_from_samples(independent, realized)
            rows.append(
                {
                    "pair": pair.key,
                    "ghcnd_id": station_label,
                    "fips": county_label,
                    "hedge_ratio": h,
                    "realized_residual": realized,
                    "r2j_crps": r2j,
                    "independent_r2_crps": ind,
                    "r2j_beats_independent": bool(r2j < ind),
                    "outcome_season": 2025,
                    "comparator": "deterministically permuted aligned station marginal",
                }
            )
    if not rows:
        return None
    frame = pd.DataFrame(rows).sort_values(["pair", "ghcnd_id"], kind="stable")
    destination = root / "results" / "tournament" / "joint_check.parquet"
    _write_frame(frame, destination)
    return destination


def run_tournament(root: Path, cfg: Any) -> dict[str, Path]:
    """Run rolling R0/R1/R2 CRPS evaluation and persist tournament artefacts.

    Only origins before the locked confirmation period are admitted here.  The
    lock is checked before any files are emitted, ensuring a failed production
    invocation cannot accidentally create selection results from holdout data.
    """
    root = Path(root)
    values, dates, labels = _load_county_panel(root)
    n_counties = _county_count(root)
    # Tournament scoring is county-only.  The daily blocks are built once in
    # the fixed D-61 basis and sliced without admitting Nebraska/check-only
    # station rows into state-month inference units.
    values = values[:, :n_counties]
    labels = labels[:n_counties]
    blocks = _subset_blocks(_load_or_build_blocks(root, cfg), np.arange(n_counties, dtype=np.intp))
    M = int(_value(cfg, "simulate", "M_tournament", 2000))
    start, end = tuple(_value(cfg, "tournament", "origins", (1991, 2022)))
    locked_start, locked_end = tuple(_value(cfg, "tournament", "holdout", (2023, 2025)))
    origins = np.arange(int(start), int(end) + 1)
    if np.any((origins >= locked_start) & (origins <= locked_end)):
        raise PermissionError("selection origins overlap locked confirmation seasons")
    seed = np.random.SeedSequence(int(getattr(cfg, "seed", 20260901)))
    all_scores: list[pd.DataFrame] = []
    origin_calibrations: list[pd.DataFrame] = []
    parameter_rows: list[dict[str, object]] = []
    parameter_outputs: list[Path] = []
    determinism: dict[str, object] | None = None
    outputs: list[Path] = []
    for pair, pair_seed in zip(PAIRS, seed.spawn(len(PAIRS)), strict=True):
        seasons, history = _pair_history(values, dates, pair)
        origin_frames: list[pd.DataFrame] = []
        for origin, origin_seed in zip(origins, pair_seed.spawn(origins.size), strict=True):
            index = int(np.searchsorted(seasons, origin))
            if index >= seasons.size or seasons[index] != origin:
                continue
            # R0/R1 are index-level comparators.  R2 is always the registered
            # daily AR/seasonal-variance simulation, never an annual-residual
            # surrogate.  Separate child sequences make the provenance of the
            # ladder explicit and leave county children stable if a rung grows.
            comparator_seed, r2_seed = origin_seed.spawn(2)
            draws = _index_comparator_draws(history, seasons, int(origin), M, comparator_seed, cfg)
            draws["R0"] = _r0_draws_from_anomalies(
                root, pair, int(origin), labels, M, comparator_seed, history, seasons
            )
            r2, daily_fit = _daily_r2_draws(
                values, dates, blocks, pair, int(origin), M, cfg, r2_seed
            )
            draws["R2"] = r2
            params_dir = root / "results" / "models" / "params"
            mean_path = params_dir / f"mean_{pair.key}_{origin}.npy"
            ar_path = params_dir / f"ar_{pair.key}_{origin}.npz"
            _save_npy(mean_path, daily_fit.mean_coef)
            _save_npz(
                ar_path,
                coef=daily_fit.ar.coef,
                order=daily_fit.ar.order,
                bic=daily_fit.ar.bic,
            )
            fit_dates = pd.DatetimeIndex(pd.to_datetime(dates))[daily_fit.fit_mask]
            parameter_rows.append(
                {
                    "pair": pair.key,
                    "origin": int(origin),
                    "fit_through": str(fit_dates[-1].date()),
                    "z_start": str(fit_dates[0].date()),
                    "z_end": str(fit_dates[-1].date()),
                    "z_n_days": int(daily_fit.z.shape[0]),
                    "z_n_series": int(daily_fit.z.shape[1]),
                    "z_sha256": hashlib.sha256(memoryview(daily_fit.z).cast("B")).hexdigest(),
                    "mean_path": str(mean_path.relative_to(root)),
                    "ar_path": str(ar_path.relative_to(root)),
                    "daily_model": "R2",
                }
            )
            parameter_outputs.extend((mean_path, ar_path))
            if determinism is None:
                replay_seed = np.random.SeedSequence(
                    r2_seed.entropy, spawn_key=r2_seed.spawn_key, pool_size=r2_seed.pool_size
                )
                replay, _ = _daily_r2_draws(
                    values, dates, blocks, pair, int(origin), M, cfg, replay_seed
                )
                first_bytes = r2.tobytes(order="C")
                replay_bytes = replay.tobytes(order="C")
                determinism = {
                    "pair": pair.key,
                    "origin": int(origin),
                    "M": M,
                    "n_counties": n_counties,
                    "first_sha256": hashlib.sha256(first_bytes).hexdigest(),
                    "replay_sha256": hashlib.sha256(replay_bytes).hexdigest(),
                    "byte_equal": first_bytes == replay_bytes,
                    "rung": "R2_daily",
                }
                if not determinism["byte_equal"]:
                    raise RuntimeError("daily R2 replay was not byte-for-byte deterministic")
            origin_calibrations.append(
                _daily_calibration_by_origin(daily_fit, labels, pair, int(origin))
            )
            # Origin samples are evaluation scratch space.  Scores are the
            # durable audit artefact; retaining 448 large matrices offers no
            # additional reproducibility because their seeds and config are
            # recorded in the manifest and regenerate them byte-for-byte.
            origin_frames.append(
                _score_frame(
                    draws, history[index, :n_counties], labels[:n_counties], pair, int(origin)
                )
            )
        frame = pd.concat(origin_frames, ignore_index=True) if origin_frames else pd.DataFrame()
        score_path = root / "results" / "tournament" / "scores" / f"{pair.key}.parquet"
        _write_frame(frame, score_path)
        all_scores.append(frame)
        outputs.append(score_path)
    score_data = pd.concat(all_scores, ignore_index=True) if all_scores else pd.DataFrame()
    selection = tournament_selection(
        score_data,
        B=int(_value(cfg, "tournament", "B", 1000)),
        level=float(_value(cfg, "tournament", "level", 0.90)),
        seed=int(getattr(cfg, "seed", 20260901)),
    )
    # ``skill`` is the continuous map/model-card value for the rung selected
    # at the unit.  Keep both stepwise skills as the audit trail.
    selection["skill"] = np.where(
        selection["rung_selected"].eq("R2"),
        selection["skill_r2_r1"],
        np.where(selection["rung_selected"].eq("R1"), selection["skill_r1_r0"], 0.0),
    )
    selection["n_counties"] = [
        int(
            score_data.loc[
                score_data["pair"].eq(pair) & score_data["state"].eq(state), "fips"
            ].nunique()
        )
        for pair, state in zip(selection["pair"], selection["state"], strict=True)
    ]
    selection_path = root / "results" / "tournament" / "selection.parquet"
    _write_frame(selection, selection_path)
    outputs.append(selection_path)
    parameter_metadata_path = root / "results" / "models" / "params" / "tournament_metadata.parquet"
    _write_frame(pd.DataFrame(parameter_rows), parameter_metadata_path)
    parameter_outputs.append(parameter_metadata_path)
    # Section 7.3's site diagnostic covers counties plus the 13 listed CME
    # stations (not the five Nebraska check-only stations).
    calibration_path = root / "results" / "tournament" / "calibration.parquet"
    preserve_daily = False
    if calibration_path.exists():
        existing = pd.read_parquet(calibration_path)
        preserve_daily = (
            len(existing) == n_counties + 13
            and "diagnostic_basis" in existing
            and existing["diagnostic_basis"].eq("daily_R2_standardized_innovation").all()
        )
    if not preserve_daily:
        calibration_labels = labels[: min(labels.size, n_counties + 13)]
        calibration_seasons, calibration_history = _pair_history(
            values[:, : calibration_labels.size], dates, PAIRS[0]
        )
        calibration = _calibration_rows(
            calibration_history, calibration_seasons, calibration_labels
        )
        _write_frame(calibration, calibration_path)
    calibration_by_origin_path = root / "results" / "tournament" / "calibration_by_origin.parquet"
    calibration_detail = (
        pd.concat(origin_calibrations, ignore_index=True)
        if origin_calibrations
        else pd.DataFrame(
            columns=[
                "pair",
                "origin",
                "series",
                "skewness",
                "excess_kurtosis",
                "ljung_box_q10",
                "mean_z2",
                "variance_regime_ratio",
                "diagnostic_basis",
            ]
        )
    )
    calibration_by_origin = (
        calibration_detail.groupby(["pair", "origin"], as_index=False)
        .agg(
            n_series=("series", "size"),
            skewness=("skewness", "mean"),
            excess_kurtosis=("excess_kurtosis", "mean"),
            ljung_box_q10=("ljung_box_q10", "mean"),
            mean_z2=("mean_z2", "mean"),
            variance_regime_ratio=("variance_regime_ratio", "mean"),
            diagnostic_basis=("diagnostic_basis", "first"),
        )
        .sort_values(["pair", "origin"], kind="stable")
    )
    _write_frame(calibration_by_origin, calibration_by_origin_path)
    holdout_path = root / "results" / "tournament" / "holdout_check.json"
    holdout_path.parent.mkdir(parents=True, exist_ok=True)
    unlocked = os.environ.get("WBA_UNLOCK_HOLDOUT") == "1"
    holdout: dict[str, object] = {
        "locked": not unlocked,
        "holdout": [int(locked_start), int(locked_end)],
    }
    if unlocked:
        confirmation: list[dict[str, object]] = []
        selected = selection.set_index(["pair", "state"])["rung_selected"].to_dict()
        for pair, pair_seed in zip(PAIRS, seed.spawn(len(PAIRS)), strict=True):
            seasons, history = _pair_history(values, dates, pair)
            rows: list[dict[str, object]] = []
            for origin, child in zip(
                range(int(locked_start), int(locked_end) + 1), pair_seed.spawn(3), strict=True
            ):
                index = int(np.searchsorted(seasons, origin))
                if index >= seasons.size or seasons[index] != origin:
                    continue
                comparator_seed, r2_seed = child.spawn(2)
                draws = _index_comparator_draws(history, seasons, origin, M, comparator_seed, cfg)
                draws["R0"] = _r0_draws_from_anomalies(
                    root, pair, origin, labels, M, comparator_seed, history, seasons
                )
                draws["R2"], _ = _daily_r2_draws(
                    values, dates, blocks, pair, origin, M, cfg, r2_seed
                )
                for column, fips in enumerate(labels[:n_counties]):
                    rung = selected.get((pair.key, str(fips)[:2]), "R0")
                    y = history[index, column]
                    if (
                        np.isfinite(y)
                        and np.isfinite(draws[rung][column]).all()
                        and np.isfinite(draws["R0"][column]).all()
                    ):
                        rows.append(
                            {
                                "selected": crps_from_samples(np.sort(draws[rung][column]), y),
                                "r0": crps_from_samples(np.sort(draws["R0"][column]), y),
                            }
                        )
            if rows:
                table = pd.DataFrame(rows)
                confirmation.append(
                    {
                        "pair": pair.key,
                        "n_cells": int(len(table)),
                        "selected_crps": float(table.selected.mean()),
                        "r0_crps": float(table.r0.mean()),
                        "skill_vs_r0": float(1 - table.selected.sum() / table.r0.sum()),
                    }
                )
        holdout["confirmation"] = confirmation
        holdout["note"] = "Unlocked confirmation only; no holdout values entered selection."
    else:
        holdout["note"] = "confirmation is run only with WBA_UNLOCK_HOLDOUT=1"
    holdout_path.write_text(json.dumps(holdout, sort_keys=True) + "\n", encoding="utf-8")
    power_path = root / "results" / "tournament" / "power.json"
    power_path.parent.mkdir(parents=True, exist_ok=True)
    power_path.write_text(
        json.dumps(
            _power_statement(score_data, len(origins), int(getattr(cfg, "seed", 20260901))),
            sort_keys=True,
        )
        + "\n"
    )
    determinism_path = root / "results" / "tournament" / "determinism.json"
    determinism_path.write_text(
        json.dumps(determinism or {"byte_equal": False}, sort_keys=True) + "\n", encoding="utf-8"
    )
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_rss_bytes = peak_rss if sys.platform == "darwin" else peak_rss * 1024
    benchmark_path = root / "results" / "tournament" / "benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "workers_configured": int(_value(cfg, "simulate", "workers", 8)),
                "workers_effective": 1,
                "peak_rss_bytes": int(peak_rss_bytes),
                "max_rss_gb": float(_value(cfg, "simulate", "max_rss_gb", 12)),
                "execution": "serial daily fits; model state is not duplicated across workers",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    outputs.extend(
        (
            calibration_path,
            calibration_by_origin_path,
            holdout_path,
            power_path,
            determinism_path,
            benchmark_path,
        )
    )
    outputs.extend(parameter_outputs)
    _manifest(root, cfg, "tournament", outputs, unlocked=unlocked)
    return {"selection": selection_path, "calibration": calibration_path, "power": power_path}


def run_site_simulation(root: Path, cfg: Any) -> dict[str, Path]:
    """Compatibility wrapper for the registered production daily R2j path."""

    from .run_daily import run_site_daily

    return run_site_daily(Path(root), cfg)
