"""Chunked production R2j scenarios with one global daily innovation plan.

This module deliberately keeps daily paths ephemeral.  A full fit is shared,
then each county chunk is propagated over the same rows and emits only its 14
monthly index columns plus two explicitly requested audit paths.
"""

from __future__ import annotations

import hashlib
import json
import resource
import sys
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import numpy as np
import pandas as pd

from weather_basis.contracts.registry import load_frozen_vintage
from weather_basis.models.fit_cache import FitCache, FitRequest, numerical_environment
from weather_basis.models.residual import seasonal_sigma
from weather_basis.models.seasonal_mean import elapsed_days, predict
from weather_basis.models.simulate import block_plan
from weather_basis.provenance.ids import content_id, file_sha256

from .common import (
    CommonScenarioPlan,
    DailyScenarioPaths,
    _daily,
    _dates,
    _location_ids,
    _scenario_set,
)
from .global_plan import build_global_season_plan

PAIR_ORDER = (
    ("HDD-10", "HDD", 10),
    ("HDD-11", "HDD", 11),
    ("HDD-12", "HDD", 12),
    ("HDD-01", "HDD", 1),
    ("HDD-02", "HDD", 2),
    ("HDD-03", "HDD", 3),
    ("HDD-04", "HDD", 4),
    ("CDD-04", "CDD", 4),
    ("CDD-05", "CDD", 5),
    ("CDD-06", "CDD", 6),
    ("CDD-07", "CDD", 7),
    ("CDD-08", "CDD", 8),
    ("CDD-09", "CDD", 9),
    ("CDD-10", "CDD", 10),
)


def _rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _fit_request(root: Path, cutoff: pd.Timestamp, labels: tuple[str, ...]) -> FitRequest:
    panel = root / "data" / "panel"
    return FitRequest(
        cutoff=str(cutoff.date()),
        panel_id="sha256:" + file_sha256(panel / "tavg_f32.npy"),
        series_ids=labels,
        support_hash=content_id(
            {
                "dates": file_sha256(panel / "dates.npy"),
                "fips": file_sha256(panel / "fips.npy"),
                "stations": file_sha256(panel / "station_ids.npy"),
                "station_values": file_sha256(panel / "stations_tbar_f32.npy"),
                "cutoff": str(cutoff.date()),
            }
        ),
        model_spec={
            "mean_months": 480,
            "residual_years": 30,
            "ar_orders": [1, 2, 3, 5],
            "logvar_harmonics": 2,
            "logvar_epsilon": 1.0e-6,
        },
        producer_fingerprint=content_id(
            {
                "daily": file_sha256(root / "src/weather_basis/models/daily.py"),
                "r2j_production": file_sha256(Path(__file__)),
            }
        ),
        numerical_environment=numerical_environment(),
    )


def _propagate_chunk(
    *,
    z: np.ndarray,
    plan_rows: np.ndarray,
    sigma: np.ndarray,
    mean: np.ndarray,
    coefficients: np.ndarray,
    initial: np.ndarray,
    dates: pd.DatetimeIndex,
    audit_count: int,
    accumulate_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Preserve V1 AR order: sigma-scales innovation before raw-residual AR."""

    paths, days = plan_rows.shape
    width, lags = coefficients.shape
    state = np.repeat(initial[:, None, :], paths, axis=1)
    totals = np.zeros((paths, width, len(PAIR_ORDER)), dtype=np.float64)
    audit = np.empty((audit_count, days, width), dtype=np.float32)
    months = dates.month.to_numpy()
    accumulate = (
        np.ones(days, dtype=bool) if accumulate_mask is None else np.asarray(accumulate_mask)
    )
    if accumulate.shape != (days,) or accumulate.dtype != bool:
        raise ValueError("accumulate_mask must be one boolean per simulated day")
    columns = np.arange(width)
    for day in range(days):
        innovation = z[plan_rows[:, day, None], columns[None, :]] * sigma[day][None, :]
        residual = innovation.copy()
        for lag in range(lags):
            residual += state[lag] * coefficients[None, :, lag]
        if lags:
            state[1:] = state[:-1]
            state[0] = residual
        temperature = mean[day][None, :] + residual
        audit[:, day] = temperature[:audit_count]
        for index, (_, kind, month) in enumerate(PAIR_ORDER):
            if accumulate[day] and months[day] == month:
                totals[:, :, index] += (
                    np.maximum(65.0 - temperature, 0.0)
                    if kind == "HDD"
                    else np.maximum(temperature - 65.0, 0.0)
                )
    return totals.astype(np.float32), audit


def _last_complete_raw_state(
    raw_history: np.ndarray, history_dates: pd.DatetimeIndex, lags: int
) -> tuple[np.ndarray, tuple[str, ...]]:
    """Return each series' latest observed AR state, newest residual first.

    Stations can have a short terminal reporting gap in the frozen panel.  We
    retain their last fully observed state rather than introducing a fill or an
    invalid NaN state; a series without a complete state is rejected.
    """

    values = np.asarray(raw_history, dtype=float)
    if values.ndim != 2 or lags < 1 or len(history_dates) != values.shape[0]:
        raise ValueError("raw history and AR state dimensions must agree")
    state = np.empty((lags, values.shape[1]), dtype=float)
    endpoints: list[str] = []
    for series in range(values.shape[1]):
        finite = np.isfinite(values[:, series])
        ends = np.flatnonzero(
            np.convolve(finite.astype(np.int8), np.ones(lags, dtype=np.int8), mode="valid")
            == lags
        )
        if not ends.size:
            raise ValueError(f"series {series} lacks {lags} consecutive observed residuals")
        end = int(ends[-1]) + lags - 1
        state[:, series] = values[end - np.arange(lags), series]
        endpoints.append(str(history_dates[end].date()))
    if not np.all(np.isfinite(state)):
        raise ValueError("initial AR state must be finite")
    return state, tuple(endpoints)


def r2j_raw_residual_horizon(
    *,
    history_dates: np.ndarray | pd.DatetimeIndex,
    standardized_residuals: np.ndarray,
    target_mean: np.ndarray,
    target_sigma: np.ndarray,
    raw_initial_state: np.ndarray,
    ar_coefficients: np.ndarray,
    location_ids: tuple[str, ...],
    plan: CommonScenarioPlan,
    data_vintage_id: str,
    model_spec_id: str,
) -> DailyScenarioPaths:
    """Small-horizon adapter with the production sigma-before-AR semantics.

    R04 uses this bounded adapter for origin-specific validation; it is not a
    national storage path and deliberately returns daily paths for its small
    registered panel only.
    """

    locations = _location_ids(location_ids)
    history = _dates(history_dates)
    z = _daily(standardized_residuals, history, locations)
    mean = _daily(target_mean, plan.dates, locations)
    sigma = _daily(target_sigma, plan.dates, locations)
    coefficients = np.asarray(ar_coefficients, dtype=float)
    initial = np.asarray(raw_initial_state, dtype=float)
    if coefficients.ndim != 2 or coefficients.shape[0] != len(locations):
        raise ValueError("AR coefficients must be (locations, lags)")
    if initial.shape != (coefficients.shape[1], len(locations)):
        raise ValueError("raw initial residual state must be (lags, locations)")
    valid = np.flatnonzero(np.all(np.isfinite(z), axis=1))
    if valid.size < len(plan.dates):
        raise ValueError("R2j horizon lacks complete joint innovation support")
    rows = block_plan(
        np.random.default_rng(plan.seed),
        M=plan.scenario_count,
        n_days=len(plan.dates),
        mean_block=7,
        candidate_days=valid,
    ).indices
    values = np.empty((plan.scenario_count, len(plan.dates), len(locations)), dtype=np.float64)
    state = np.repeat(initial[:, None, :], plan.scenario_count, axis=1)
    for day in range(len(plan.dates)):
        innovation = z[rows[:, day, None], np.arange(len(locations))[None, :]] * sigma[day]
        residual = innovation.copy()
        for lag in range(coefficients.shape[1]):
            residual += state[lag] * coefficients[None, :, lag]
        if coefficients.shape[1]:
            state[1:] = state[:-1]
            state[0] = residual
        values[:, day] = mean[day] + residual
    scenario_ids = tuple(
        f"{plan.plan_id[:12]}-r2jraw-{index:05d}" for index in range(plan.scenario_count)
    )
    scenario_set = _scenario_set(
        plan,
        scenario_ids=scenario_ids,
        location_ids=locations,
        scenario_type="physical_predictive",
        data_vintage_id=data_vintage_id,
        model_spec_ids=(model_spec_id, "r2j-raw-residual-before-ar-v1"),
        identity_inputs={"row_plan_sha256": hashlib.sha256(rows.tobytes()).hexdigest()},
    )
    return DailyScenarioPaths(
        scenario_set=scenario_set, dates=plan.dates, location_ids=locations, values=values
    )


def prepare_r2j_fit(
    root: Path | str,
    *,
    valuation_asof: str = "2026-07-01",
    allow_fit: bool = True,
) -> dict[str, object]:
    """Materialize or identify the exact common-cutoff production fit.

    Stage execution calls this once in ``models.fit``.  Scenario production can
    then require its returned parent identity and only load the immutable cache.
    """

    root = Path(root)
    panel = root / "data" / "panel"
    dates = pd.DatetimeIndex(np.load(panel / "dates.npy", mmap_mode="r", allow_pickle=False))
    fips = tuple(
        str(item) for item in np.load(panel / "fips.npy", mmap_mode="r", allow_pickle=False)
    )
    station_ids = tuple(
        str(item) for item in np.load(panel / "station_ids.npy", mmap_mode="r", allow_pickle=False)
    )
    cutoff = pd.Timestamp(valuation_asof) - pd.Timedelta(days=31)
    request = _fit_request(root, cutoff, fips + station_ids)
    cache = FitCache(root / "var" / "cache" / "v2" / "fits")
    cached = cache.load(request)
    cache_hit = cached is not None
    if cached is None:
        if not allow_fit:
            raise FileNotFoundError(f"required R2j fit is absent: {request.fit_id}")
        counties = np.load(panel / "tavg_f32.npy", mmap_mode="r", allow_pickle=False)
        stations = np.load(panel / "stations_tbar_f32.npy", mmap_mode="r", allow_pickle=False)
        from weather_basis.models.daily import fit_daily
        from weather_basis.models.run_daily import _load_or_build_blocks

        cache.get_or_fit(
            request,
            lambda: fit_daily(
                SimpleNamespace(values=np.concatenate((counties, stations), axis=1), dates=dates),
                fit_through=cutoff,
                mean_blocks_stats=_load_or_build_blocks(root, SimpleNamespace()),
            ),
        )
    vintage = load_frozen_vintage(root)
    return {
        "schema_version": "2.0",
        "kind": "r2j-fit-parent",
        "fit_id": request.fit_id,
        "fit_request": asdict(request),
        "fit_cache_path": str(cache.directory(request).relative_to(root)),
        "fit_cache_hit": cache_hit,
        "observation_cutoff": str(cutoff.date()),
        "valuation_asof": valuation_asof,
        "data_vintage_id": vintage.vintage_id,
        "location_ids_sha256": hashlib.sha256("\n".join(fips + station_ids).encode()).hexdigest(),
    }


def build_r2j_production(
    root: Path | str,
    out: Path | str,
    *,
    county_ids: tuple[str, ...] | None = None,
    paths: int = 2_000,
    chunk_size: int = 128,
    audit_count: int = 2,
    valuation_asof: str = "2026-07-01",
    seed: int = 20260905,
    fit_parent: Mapping[str, object] | None = None,
    allow_fit: bool = True,
) -> dict[str, object]:
    """Build public/offline-prefix R2j monthly chunks without a daily cube."""

    root, out = Path(root), Path(out)
    started = perf_counter()
    if paths not in (512, 2_000, 10_000):
        raise ValueError(
            "paths must be the registered 512 benchmark, 2,000 public or 10,000 offline prefix"
        )
    panel = root / "data" / "panel"
    dates = pd.DatetimeIndex(np.load(panel / "dates.npy", mmap_mode="r", allow_pickle=False))
    fips = tuple(
        str(item) for item in np.load(panel / "fips.npy", mmap_mode="r", allow_pickle=False)
    )
    station_ids = tuple(
        str(item) for item in np.load(panel / "station_ids.npy", mmap_mode="r", allow_pickle=False)
    )
    requested = tuple(str(item) for item in (county_ids or fips))
    lookup = {item: index for index, item in enumerate(fips)}
    missing = tuple(item for item in requested if item not in lookup)
    if missing:
        raise ValueError(f"requested counties lack frozen support: {missing}")
    if chunk_size < 1 or audit_count < 1:
        raise ValueError("chunk_size and audit_count must be positive")
    global_plan = build_global_season_plan(
        root, offline_paths=10_000, valuation_asof=valuation_asof, seed=seed
    )
    vintage = load_frozen_vintage(root)
    horizon = global_plan.common_plan.dates
    # The frozen station panel ends 2026-05-31.  Conditioning every location
    # there, then simulating the shared June bridge, avoids mixing county and
    # station information sets at the July 1 valuation boundary.
    cutoff = horizon[0] - pd.Timedelta(days=31)
    simulation_dates = pd.date_range(cutoff + pd.Timedelta(days=1), horizon[-1], freq="D")
    accumulate_mask = simulation_dates >= horizon[0]
    counties = np.load(panel / "tavg_f32.npy", mmap_mode="r", allow_pickle=False)
    stations = np.load(panel / "stations_tbar_f32.npy", mmap_mode="r", allow_pickle=False)
    all_values = np.concatenate((counties, stations), axis=1)
    labels = fips + station_ids
    prepared_fit = prepare_r2j_fit(root, valuation_asof=valuation_asof, allow_fit=allow_fit)
    if fit_parent is not None:
        for key in ("kind", "fit_id", "observation_cutoff", "data_vintage_id"):
            if fit_parent.get(key) != prepared_fit[key]:
                raise ValueError(f"supplied R2j fit parent differs in {key}")
    request = _fit_request(root, cutoff, labels)
    cache = FitCache(root / "var" / "cache" / "v2" / "fits")
    fit = cache.load(request)
    if fit is None:
        raise RuntimeError("prepared R2j fit was not published to cache")
    history_dates = dates[fit.fit_mask]
    valid = np.all(np.isfinite(fit.z), axis=1)
    candidates = np.flatnonzero(valid)
    if candidates.size < len(horizon):
        raise ValueError("R2j global innovation support lacks one complete common horizon")
    rows = block_plan(
        np.random.default_rng(np.random.SeedSequence(seed).spawn(1)[0]),
        M=10_000,
        n_days=len(simulation_dates),
        mean_block=7,
        candidate_days=candidates,
    ).indices[:paths]
    plan = CommonScenarioPlan(
        valuation_asof=valuation_asof,
        horizon_start=str(horizon[0].date()),
        horizon_end=str(horizon[-1].date()),
        scenario_count=paths,
        seed=seed,
        generator_spec_id="r2j-common-horizon-production-bridged-v2",
        location_universe_id=global_plan.common_plan.location_universe_id,
    )
    scenario_ids = tuple(f"{plan.plan_id[:12]}-r2j-{index:05d}" for index in range(paths))
    scenario_set = _scenario_set(
        plan,
        scenario_ids=scenario_ids,
        location_ids=labels,
        scenario_type="physical_predictive",
        data_vintage_id=vintage.vintage_id,
        model_spec_ids=("R2j", request.fit_id, "r2j-raw-residual-before-ar-v1"),
        identity_inputs={"row_plan_sha256": hashlib.sha256(rows.tobytes()).hexdigest()},
    )
    future_t = elapsed_days(simulation_dates)
    mean_all = predict(fit.mean_coef, future_t)
    sigma_all = seasonal_sigma(fit.logvar, simulation_dates.dayofyear.to_numpy())
    raw_history = np.asarray(all_values, dtype=np.float64)[fit.fit_mask] - predict(
        fit.mean_coef, elapsed_days(history_dates)
    )
    initial_all, initial_state_dates = _last_complete_raw_state(
        raw_history, history_dates, fit.ar.coef.shape[1]
    )
    if any(date != str(cutoff.date()) for date in initial_state_dates):
        raise ValueError("all locations must share the declared observation cutoff")
    out.mkdir(parents=True, exist_ok=True)
    chunks: dict[str, str] = {}
    station_start = len(fips)
    station_totals, station_audit = _propagate_chunk(
        z=fit.z[:, station_start:],
        plan_rows=rows,
        sigma=sigma_all[:, station_start:],
        mean=mean_all[:, station_start:],
        coefficients=fit.ar.coef[station_start:],
        initial=initial_all[:, station_start:],
        dates=simulation_dates,
        audit_count=audit_count,
        accumulate_mask=accumulate_mask,
    )
    if not np.all(np.isfinite(station_totals)) or not np.all(np.isfinite(station_audit)):
        raise RuntimeError("station propagation produced non-finite values")
    np.savez_compressed(
        out / "stations_14pair.npz",
        values=station_totals.transpose(0, 2, 1).reshape(paths, -1),
        scenario_ids=np.asarray(scenario_ids),
        entity_ids=np.asarray(
            [f"{station}:{key}" for key, _, _ in PAIR_ORDER for station in station_ids]
        ),
        parent_scenario_set_id=np.asarray([scenario_set.scenario_set_id]),
        units=np.asarray(["degree_days"]),
    )
    np.save(out / "global_innovation_rows.npy", rows, allow_pickle=False)
    audit_written = False
    for start in range(0, len(requested), chunk_size):
        selected = requested[start : start + chunk_size]
        indexes = np.asarray([lookup[item] for item in selected])
        totals, audit = _propagate_chunk(
            z=fit.z[:, indexes],
            plan_rows=rows,
            sigma=sigma_all[:, indexes],
            mean=mean_all[:, indexes],
            coefficients=fit.ar.coef[indexes],
            initial=initial_all[:, indexes],
            dates=simulation_dates,
            audit_count=audit_count,
            accumulate_mask=accumulate_mask,
        )
        if not np.all(np.isfinite(totals)) or not np.all(np.isfinite(audit)):
            raise RuntimeError(f"county propagation produced non-finite values for {selected}")
        for local, county in enumerate(selected):
            filename = f"county_{county}.npz"
            np.savez_compressed(
                out / filename,
                values=totals[:, local, :],
                scenario_ids=np.asarray(scenario_ids),
                entity_ids=np.asarray([f"{county}:{key}" for key, _, _ in PAIR_ORDER]),
                parent_scenario_set_id=np.asarray([scenario_set.scenario_set_id]),
                units=np.asarray(["degree_days"]),
            )
            chunks[county] = filename
        if not audit_written:
            np.savez_compressed(
                out / "audit_daily_paths.npz",
                values=audit,
                dates=simulation_dates.values.astype("datetime64[D]"),
                location_ids=np.asarray(selected),
                scenario_ids=np.asarray(scenario_ids[:audit_count]),
            )
            audit_written = True
    manifest = {
        "schema_version": "2.0",
        "kind": "r2j-production-stream",
        "random_seed": seed,
        "seed_id": f"r2j-production-bridged-v2-{seed}",
        "seed_schema_version": "v2-seed-1",
        "output_storage_dtype": "float32",
        "audit_storage_dtype": "float32",
        "accumulation_dtype": "float64",
        "canonical_matrix_dtype": "float64",
        "scenario_set": scenario_set.to_dict(),
        "global_plan_id": global_plan.plan_id,
        "data_vintage_id": vintage.vintage_id,
        "fit_parent": prepared_fit,
        "fit_request": asdict(request),
        "fit_id": request.fit_id,
        "fit_cache_hit": bool(prepared_fit["fit_cache_hit"]),
        "row_plan_sha256": hashlib.sha256(rows.tobytes()).hexdigest(),
        "row_plan_shape": list(rows.shape),
        "observation_cutoff": str(cutoff.date()),
        "bridge_dates": [
            str(simulation_dates[0].date()),
            str((horizon[0] - pd.Timedelta(days=1)).date()),
        ],
        "bridge_days": int((~accumulate_mask).sum()),
        "accumulation_dates": [str(horizon[0].date()), str(horizon[-1].date())],
        "initial_state_policy": "latest complete observed raw residual run; newest lag first",
        "initial_state_dates_sha256": hashlib.sha256(
            "\n".join(initial_state_dates).encode("utf-8")
        ).hexdigest(),
        "initial_state_cutoff_count": sum(
            date == str(cutoff.date()) for date in initial_state_dates
        ),
        "paths": paths,
        "offline_paths": 10_000,
        "public_paths": 2_000,
        "public_slice_rule": "offline rows, scenario_ids, and each NPZ values[0:2000]",
        "global_innovation_rows": "global_innovation_rows.npy",
        "public_prefix_row_sha256": hashlib.sha256(rows[:2_000].tobytes()).hexdigest(),
        "chunk_size": chunk_size,
        "pair_order": [key for key, _, _ in PAIR_ORDER],
        "county_chunks": chunks,
        "station_chunk": "stations_14pair.npz",
        "audit_daily_paths": "audit_daily_paths.npz",
        "source_hashes": {
            name: file_sha256(panel / name)
            for name in (
                "dates.npy",
                "fips.npy",
                "station_ids.npy",
                "tavg_f32.npy",
                "stations_tbar_f32.npy",
            )
        },
        "elapsed_seconds": perf_counter() - started,
        "peak_rss_bytes": _rss_bytes(),
        "status": "benchmark" if paths == 512 else "candidate-production-artifact",
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
