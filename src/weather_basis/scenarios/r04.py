"""Registered R04 origin-by-origin generator comparison."""
# ruff: noqa: E501, E701, E702
from __future__ import annotations

import json
import resource
import sys
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import numpy as np
import pandas as pd
import yaml

from weather_basis.contracts.calendar import PAIRS
from weather_basis.models.daily import fit_daily
from weather_basis.models.residual import seasonal_sigma
from weather_basis.models.scoring import crps_from_samples
from weather_basis.models.seasonal_mean import elapsed_days, predict
from weather_basis.provenance.ids import content_id, file_sha256
from weather_basis.schemas.scenarios import ScenarioMatrix

from .common import (
    CommonScenarioPlan,
    DailyScenarioPaths,
    build_trend_bootstrap,
    monthly_degree_day_matrix,
)
from .marginal import rank_coupled_marginals
from .r2j_production import r2j_raw_residual_horizon


def _rss() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == "darwin" else value * 1024


def _write_matrix(path: Path, matrix: ScenarioMatrix) -> None:
    np.savez_compressed(path, values=matrix.values, scenario_ids=np.asarray(matrix.scenario_ids), entity_ids=np.asarray(matrix.entity_ids), parent=np.asarray([matrix.parent_scenario_set_id]))


def _monthly_history(root: Path, labels: tuple[str, ...], origin: int) -> np.ndarray:
    columns = []
    for entity in labels:
        location, pair = entity.split(":")
        source, key = ("county", "fips") if len(location) == 5 else ("station", "ghcnd_id")
        frame = pd.read_parquet(root / "results" / "indices" / f"{source}_{pair}.parquet")
        if key == "fips": frame[key] = frame[key].astype(str).str.zfill(5)
        columns.append(frame.loc[(frame[key].astype(str) == location) & (frame.season < origin), ["season", "index"]].set_index("season")["index"].rename(entity))
    values = pd.concat(columns, axis=1).dropna().to_numpy(dtype=float)
    if len(values) < 8: raise ValueError("insufficient complete training monthly vectors")
    return values


def _energy(samples: np.ndarray, observed: np.ndarray, scale: np.ndarray) -> float:
    x, y = samples / scale, observed / scale
    first = np.linalg.norm(x - y, axis=1).mean()
    return float(first - 0.5 * np.mean([np.linalg.norm(x - row, axis=1).mean() for row in x]))


def _scores(matrix: ScenarioMatrix, observed: np.ndarray, scale: np.ndarray) -> dict[str, object]:
    crps = [crps_from_samples(np.sort(matrix.values[:, j]), observed[j]) for j in range(matrix.values.shape[1])]
    return {"per_column_crps": dict(zip(matrix.entity_ids, (float(value) for value in crps), strict=True)), "mean_crps": float(np.mean(crps)), "sum_crps": float(np.sum(crps)), "energy_score": _energy(matrix.values, observed, scale)}


def run_r04_pilot(root: Path | str, out: Path | str, *, origins: tuple[int, ...] = (2019, 2020, 2021), paths: int = 512) -> dict[str, object]:
    """Score three predeclared generators against one unreplicated realized vector."""
    root, out = Path(root), Path(out)
    protocol = yaml.safe_load((root / "config/research/r04-common-scenarios.yaml").read_text())
    if tuple(protocol["origins"]) != origins or int(protocol["paths"]) != paths: raise ValueError("R04 must use frozen origins and path count")
    started = perf_counter(); out.mkdir(parents=True, exist_ok=True)
    panel = root / "data/panel"; dates = pd.DatetimeIndex(np.load(panel / "dates.npy", mmap_mode="r", allow_pickle=False))
    fips = np.load(panel / "fips.npy", mmap_mode="r", allow_pickle=False).astype("U"); locations_c = tuple(protocol["representative_counties"]); lookup = {str(x): i for i, x in enumerate(fips)}
    locations_s = tuple(str(x) for x in np.load(panel / "station_ids.npy", mmap_mode="r", allow_pickle=False)); locations = locations_c + locations_s
    values = np.concatenate((np.load(panel / "tavg_f32.npy", mmap_mode="r", allow_pickle=False)[:, [lookup[x] for x in locations_c]], np.load(panel / "stations_tbar_f32.npy", mmap_mode="r", allow_pickle=False)), axis=1)
    rows = []
    for origin in origins:
        t0 = perf_counter(); directory = out / f"origin-{origin}"; directory.mkdir(exist_ok=True)
        cutoff = pd.Timestamp(f"{origin}-06-30"); train = dates <= cutoff; horizon = pd.date_range(f"{origin}-07-01", f"{origin + 1}-06-30", freq="D"); held = (dates >= horizon[0]) & (dates <= horizon[-1]); actual_daily = values[held]
        if actual_daily.shape != (len(horizon), len(locations)) or not np.isfinite(actual_daily).all():
            rows.append({"origin": origin, "status": "unavailable", "reason": "missing_heldout_common_daily_support", "fit_cutoff": str(cutoff.date())}); continue
        plan = CommonScenarioPlan(valuation_asof=str(horizon[0].date()), horizon_start=str(horizon[0].date()), horizon_end=str(horizon[-1].date()), scenario_count=paths, seed=int(protocol["seed"]) + origin, location_universe_id="r04-registered-subset-v2")
        fitted = fit_daily(SimpleNamespace(values=values[train], dates=dates[train]), fit_through=cutoff)
        np.savez_compressed(directory / "fitted_params.npz", mean_coef=fitted.mean_coef, logvar=fitted.logvar, ar_coef=fitted.ar.coef, fit_mask=fitted.fit_mask)
        mean, sigma = predict(fitted.mean_coef, elapsed_days(horizon)), seasonal_sigma(fitted.logvar, horizon.dayofyear.to_numpy())
        history_dates = dates[train][fitted.fit_mask]
        raw_history = values[train][fitted.fit_mask] - predict(fitted.mean_coef, elapsed_days(history_dates))
        r2daily = r2j_raw_residual_horizon(history_dates=history_dates, standardized_residuals=fitted.z, target_mean=mean, target_sigma=sigma, raw_initial_state=raw_history[-fitted.ar.coef.shape[1]:], ar_coefficients=fitted.ar.coef, location_ids=locations, plan=plan, data_vintage_id="frozen-panel-2026-09-02", model_spec_id=f"r04-r2j-raw-residual-through-{cutoff.date()}")
        r2j = monthly_degree_day_matrix(r2daily)
        common = monthly_degree_day_matrix(build_trend_bootstrap(dates=dates[train], values=values[train], location_ids=locations, plan=plan, data_vintage_id="frozen-panel-2026-09-02"))
        history = _monthly_history(root, r2j.entity_ids, origin)
        rank = rank_coupled_marginals(historical_indexes=history, entity_ids=r2j.entity_ids, scenario_set=r2daily.scenario_set, seed=int(protocol["seed"]) + origin).matrix
        observed_set = replace(r2daily.scenario_set, scenario_ids=(f"observed-{origin}",), probability_weights=(1.0,))
        actual = monthly_degree_day_matrix(DailyScenarioPaths(scenario_set=observed_set, dates=horizon, location_ids=locations, values=actual_daily[None, :, :])).values[0]
        scale = np.maximum(np.std(history, axis=0), 1.0)
        for name, matrix in (("r2j", r2j), ("common_year", common), ("rank", rank)): _write_matrix(directory / f"{name}_monthly.npz", matrix)
        files = {name: file_sha256(directory / name) for name in ("fitted_params.npz", "r2j_monthly.npz", "common_year_monthly.npz", "rank_monthly.npz")}
        rows.append({"origin": origin, "status": "complete", "fit_cutoff": str(cutoff.date()), "scoreability": "complete", "pairs": [p.key for p in PAIRS], "columns": len(r2j.entity_ids), "training_vectors": len(history), "scores": {"r2j": _scores(r2j, actual, scale), "common_year_trend": _scores(common, actual, scale), "rank_coupled_monthly": _scores(rank, actual, scale)}, "runtime_seconds": perf_counter() - t0, "peak_rss_bytes": _rss(), "files": files})
    complete = [row for row in rows if row["status"] == "complete"]
    names = ("r2j", "common_year_trend", "rank_coupled_monthly")
    summary = {"n_registered_origins": len(origins), "n_scoreable_origins": len(complete), "mean_scores": {name: {metric: float(np.mean([row["scores"][name][metric] for row in complete])) for metric in ("mean_crps", "energy_score")} for name in names} if complete else {}}
    result = {"experiment_id": protocol["experiment_id"], "protocol_id": content_id(protocol), "status": "executed", "producer": "r04-origin-score-v3-r2j-raw-residual-before-ar", "prior_artifact_status": protocol["prior_artifact_status"], "rows": rows, "summary": summary, "runtime_seconds": perf_counter() - started, "peak_rss_bytes": _rss(), "disposition": "inconclusive_small_registered_origin_count; retain R2j for daily/strip support and common-year trend as tested monthly baseline"}
    (out / "report.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    # Existing stage adapters consume this stable filename; report.json is the
    # public experiment report and has identical evidence content.
    (out / "r04.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    choice = {"schema_version": "2.0", "experiment_id": protocol["experiment_id"], "protocol_id": result["protocol_id"], "producer": result["producer"], "selected_generator": "r2j-raw-residual-before-ar-v1", "monthly_alternative": "common-year-trend-bootstrap-v1", "rank_candidate": "monthly-index-only", "disposition": result["disposition"], "report_id": content_id(result)}
    (out / "accepted-generator-selection.json").write_text(json.dumps(choice, indent=2, sort_keys=True) + "\n")
    return result
