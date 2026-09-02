"""Assembly of deterministic, tabular hedge-atlas outputs (plan section 6.7)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from weather_basis.hedge.bootstrap import BootResult, stability


@dataclass(frozen=True)
class PairAtlasInput:
    """In-memory output from the rolling pass needed to produce one pair's tables."""

    pair: str
    seasons: np.ndarray
    fips: np.ndarray
    station_ids: np.ndarray
    anomalies: np.ndarray
    residuals: np.ndarray
    h: np.ndarray
    train_corr: np.ndarray
    nearest_station: np.ndarray
    pit_station: np.ndarray
    bootstrap: BootResult
    population: np.ndarray | None = None
    confidence: np.ndarray | None = None
    distance_km: np.ndarray | None = None
    short_record: np.ndarray | None = None


def _metrics(
    residual: np.ndarray, exposure: np.ndarray, seasons: np.ndarray
) -> dict[str, float | int]:
    mask = np.isfinite(residual) & np.isfinite(exposure)
    if not mask.any():
        return {
            "he": np.nan,
            "rmse": np.nan,
            "es90_upper": np.nan,
            "es90_lower": np.nan,
            "worst": np.nan,
            "worst_season": np.nan,
            "n_test": 0,
            "first_test": np.nan,
            "last_test": np.nan,
        }
    r, a, ss = residual[mask], exposure[mask], seasons[mask]
    denom = np.sum((a - a.mean()) ** 2)
    tolerance = max(np.finfo(np.float64).eps, 1.0e-12 * max(float(np.sum(a * a)), 1.0))
    if denom <= tolerance:
        he = 1.0 if np.sum(r * r) <= tolerance else 0.0
    else:
        he = 1 - np.sum(r * r) / denom
    tail_n = max(1, int(np.ceil(0.10 * len(r))))
    ordered = np.sort(r)
    worst_i = int(np.argmax(np.abs(r)))
    return {
        "he": float(he),
        "rmse": float(np.sqrt(np.mean(r * r))),
        "es90_upper": float(ordered[-tail_n:].mean()) if len(r) >= 3 else np.nan,
        "es90_lower": float(ordered[:tail_n].mean()) if len(r) >= 3 else np.nan,
        "worst": float(np.abs(r[worst_i])),
        "worst_season": int(ss[worst_i]),
        "n_test": int(len(r)),
        "first_test": int(ss.min()),
        "last_test": int(ss.max()),
    }


def _chosen_residual(residuals: np.ndarray, chosen: np.ndarray) -> np.ndarray:
    t_count, county_count, _ = residuals.shape
    out = np.full((t_count, county_count), np.nan)
    for t in range(t_count):
        valid = chosen[t] >= 0
        if valid.any():
            out[t, valid] = residuals[t, np.flatnonzero(valid), chosen[t, valid]]
    return out


def _common_bootstrap_he(
    weights: np.ndarray, residual: np.ndarray, exposure: np.ndarray, common: np.ndarray
) -> np.ndarray:
    """HE bootstrap draws after fixing one county's common eligible seasons."""
    valid = common[:, None] & np.isfinite(residual) & np.isfinite(exposure[:, None])
    r = np.where(valid, residual, 0.0)
    a = np.where(valid, exposure[:, None], 0.0)
    n = weights @ valid.astype(float)
    ssr = weights @ (r * r)
    total = weights @ a
    total2 = weights @ (a * a)
    sst = total2 - np.divide(total * total, n, out=np.full_like(total, np.nan), where=n > 0)
    tolerance = np.maximum(np.finfo(np.float64).eps, 1.0e-12 * np.maximum(total2, 1.0))
    informative = (n >= 2) & (sst > tolerance)
    ratio = np.divide(ssr, sst, out=np.full_like(ssr, np.nan), where=informative)
    degenerate = (n > 0) & ~informative
    return np.where(
        degenerate & (ssr <= tolerance), 1.0, np.where(degenerate, 0.0, 1.0 - ratio)
    )


def summarize_pair(
    data: PairAtlasInput,
    *,
    eligible_min_test: int = 10,
    stability_threshold: float = 0.60,
    hedgeable_he: float = 0.50,
    hedgeable_lb: float = 0.25,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Create pair, station, and B-level bootstrap tables from one rolling pass."""
    seasons = np.asarray(data.seasons)
    a = np.asarray(data.anomalies, dtype=float)
    r = np.asarray(data.residuals, dtype=float)
    h = np.asarray(data.h, dtype=float)
    choices = np.asarray(data.pit_station, dtype=int)
    nearest = np.asarray(data.nearest_station, dtype=int)
    if r.ndim != 3 or a.shape != r.shape[:2] or choices.shape != r.shape[:2]:
        raise ValueError("rolling tensors must be (seasons, counties, stations)")
    if seasons.shape != (r.shape[0],) or nearest.shape != (r.shape[1],):
        raise ValueError("season and county dimensions do not agree")
    pit_r = _chosen_residual(r, choices)
    nearest_choice = np.broadcast_to(nearest, choices.shape)
    near_r = _chosen_residual(r, nearest_choice)
    lower, upper = data.bootstrap.interval(data.bootstrap.he_pit)
    station_metric = [
        [_metrics(r[:, c, j], a[:, c], seasons) for j in range(r.shape[2])]
        for c in range(r.shape[1])
    ]
    station_n = np.array([[m["n_test"] for m in row] for row in station_metric])
    eligible = station_n >= eligible_min_test
    best = np.full(r.shape[1], -1, dtype=int)
    n_common = np.zeros(r.shape[1], dtype=int)
    winner_stability = np.full(r.shape[1], np.nan)
    best_he = np.full(r.shape[1], np.nan)
    for c in range(r.shape[1]):
        candidates = np.flatnonzero(eligible[c])
        if not len(candidates):
            continue
        common = np.isfinite(a[:, c]) & np.all(np.isfinite(r[:, c, candidates]), axis=1)
        n_common[c] = int(common.sum())
        if not common.any():
            continue
        common_he = np.array(
            [_metrics(r[common, c, j], a[common, c], seasons[common])["he"] for j in candidates]
        )
        if not np.isfinite(common_he).any():
            continue
        best[c] = int(candidates[np.nanargmax(common_he)])
        best_he[c] = float(np.nanmax(common_he))
        boot_he = _common_bootstrap_he(data.bootstrap.weights, r[:, c, candidates], a[:, c], common)
        winner_stability[c] = stability(
            boot_he[:, None, :], np.array([np.flatnonzero(candidates == best[c])[0]])
        )[0]
    population = np.ones(r.shape[1]) if data.population is None else np.asarray(data.population)
    confidence = (
        np.full(r.shape[1], "not_assessed", dtype=object)
        if data.confidence is None
        else np.asarray(data.confidence)
    )
    pairs: list[dict[str, object]] = []
    stations: list[dict[str, object]] = []
    for c, fips in enumerate(data.fips.astype(str)):
        pit = _metrics(pit_r[:, c], a[:, c], seasons)
        near = _metrics(near_r[:, c], a[:, c], seasons)
        chosen_h = np.array(
            [h[t, c, choices[t, c]] if choices[t, c] >= 0 else np.nan for t in range(r.shape[0])]
        )
        pairs.append(
            {
                "pair": data.pair,
                "fips": fips,
                "n_test": pit["n_test"],
                "first_test": pit["first_test"],
                "last_test": pit["last_test"],
                "station_nearest": str(data.station_ids[nearest[c]]),
                "he_nearest": near["he"],
                "station_pit": str(data.station_ids[choices[-1, c]])
                if choices[-1, c] >= 0
                else None,
                "he_pit": pit["he"],
                "he_pit_lb": lower[c],
                "he_pit_ub": upper[c],
                "h_pit": float(np.nanmean(chosen_h)),
                "rmse_pit": pit["rmse"],
                "es90_upper_pit": pit["es90_upper"],
                "es90_lower_pit": pit["es90_lower"],
                "worst_pit": pit["worst"],
                "worst_season_pit": pit["worst_season"],
                "best_pooled": str(data.station_ids[best[c]]) if best[c] >= 0 else None,
                "he_best_pooled": best_he[c],
                "n_common": n_common[c],
                "stability": winner_stability[c],
                "no_stable_proxy": bool(
                    np.isfinite(winner_stability[c]) and winner_stability[c] < stability_threshold
                ),
                "hedgeable": bool(
                    np.isfinite(pit["he"])
                    and pit["he"] >= hedgeable_he
                    and lower[c] >= hedgeable_lb
                ),
                "corr_train_last": float(np.nanmax(data.train_corr[-1, c]))
                if np.isfinite(data.train_corr[-1, c]).any()
                else np.nan,
                "confidence": confidence[c],
                "pop2020": population[c],
            }
        )
        for j, station in enumerate(data.station_ids.astype(str)):
            metric = station_metric[c][j]
            lo, hi = data.bootstrap.interval(data.bootstrap.he_station[:, c, j])
            stations.append(
                {
                    "pair": data.pair,
                    "fips": fips,
                    "station": station,
                    "he_pooled": metric["he"],
                    "he_lb": lo,
                    "he_ub": hi,
                    "h_mean": float(np.nanmean(h[:, c, j])),
                    "rmse": metric["rmse"],
                    "es90_upper": metric["es90_upper"],
                    "es90_lower": metric["es90_lower"],
                    "worst": metric["worst"],
                    "n_test": metric["n_test"],
                    "distance_km": np.nan if data.distance_km is None else data.distance_km[c, j],
                    "eligible": bool(eligible[c, j]),
                    "short_record": False
                    if data.short_record is None
                    else bool(data.short_record[j]),
                }
            )
    b_rows = [
        {
            "pair": data.pair,
            "replicate": b,
            "he_pit_mean": float(np.nanmean(data.bootstrap.he_pit[b])),
            "he_nearest_mean": float(np.nanmean(data.bootstrap.he_nearest[b])),
        }
        for b in range(data.bootstrap.he_pit.shape[0])
    ]
    return pd.DataFrame(pairs), pd.DataFrame(stations), pd.DataFrame(b_rows)


def headline(
    pairs: pd.DataFrame,
    zero_distance: pd.DataFrame,
    *,
    bootstrap_B: int,
    seed: int,
    config_hash: str,
    git_commit: str,
    atlas_run_id: str,
    thresholds: Iterable[float] = (0.25, 0.50, 0.75),
    stability_threshold: float = 0.60,
    stations: pd.DataFrame | None = None,
) -> dict[str, object]:
    """Render the pre-registered, result-derived headline payload for all pairs."""
    required = {
        "pair",
        "he_pit",
        "he_pit_lb",
        "station_pit",
        "station_nearest",
        "pop2020",
        "n_test",
        "stability",
    }
    missing = required - set(pairs.columns)
    if missing:
        raise ValueError(f"pairs is missing required columns: {sorted(missing)}")
    output: dict[str, object] = {
        "pairs": [],
        "bootstrap_B": bootstrap_B,
        "seed": seed,
        "config_hash": config_hash,
        "git_commit": git_commit,
        "atlas_run_id": atlas_run_id,
    }
    for pair, frame in pairs.groupby("pair", sort=False):
        pop = frame.pop2020.to_numpy(dtype=float)
        valid_pop = np.isfinite(pop) & (pop >= 0)
        hedgeable = (frame.he_pit >= 0.50) & (frame.he_pit_lb >= 0.25)
        differs = frame.station_pit.notna() & (frame.station_pit != frame.station_nearest)
        shares = {}
        for threshold in thresholds:
            hit = frame.he_pit >= threshold
            shares[f"{threshold:.2f}"] = {
                "counties": float(hit.mean()),
                "population": float(np.average(hit[valid_pop], weights=pop[valid_pop]))
                if valid_pop.any() and pop[valid_pop].sum()
                else np.nan,
            }
        gain = (
            frame.loc[differs, "he_pit"].to_numpy() - frame.loc[differs, "he_pit"].to_numpy()
        )  # corrected below when nearest HE is present
        if "he_nearest" in frame:
            gain = (
                frame.loc[differs, "he_pit"].to_numpy()
                - frame.loc[differs, "he_nearest"].to_numpy()
            )
        effective = (
            int(stations.loc[(stations.pair == pair) & (stations.n_test > 0), "station"].nunique())
            if stations is not None
            else int(frame.station_pit.dropna().nunique())
        )
        output["pairs"].append(
            {
                "pair": pair,
                "no_hedge_share_counties": float((~hedgeable).mean()),
                "no_hedge_share_population": float(
                    np.average((~hedgeable)[valid_pop], weights=pop[valid_pop])
                )
                if valid_pop.any() and pop[valid_pop].sum()
                else np.nan,
                "best_ne_nearest_share": float(differs.mean()),
                "switch_gain_he_median": float(np.nanmedian(gain)) if len(gain) else np.nan,
                "no_stable_proxy_share": float((frame.stability < stability_threshold).mean()),
                "threshold_shares": shares,
                "zero_distance": zero_distance.loc[zero_distance.pair == pair].to_dict(
                    orient="records"
                ),
                "n_stations_effective": effective,
                "n_counties": int(len(frame)),
                "n_test_seasons_min": int(frame.n_test.min()),
                "n_test_seasons_max": int(frame.n_test.max()),
                "bootstrap_B": bootstrap_B,
                "seed": seed,
                "config_hash": config_hash,
                "git_commit": git_commit,
                "atlas_run_id": atlas_run_id,
            }
        )
    # The two focal pairs are deliberately first; preserve caller order for all
    # remaining contracts to retain the calendar's declared ordering.
    payload_pairs = output["pairs"]
    assert isinstance(payload_pairs, list)
    focal = {"HDD-01": 0, "CDD-07": 1}
    payload_pairs.sort(key=lambda row: focal.get(str(row["pair"]), 2))
    return output


def write_headline(payload: dict[str, object], path: Path) -> None:
    """Write canonical JSON so an unchanged atlas produces unchanged bytes."""

    def clean(value: object) -> object:
        if isinstance(value, dict):
            return {str(key): clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, float) and not np.isfinite(value):
            return None
        return value

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(payload), sort_keys=True, indent=2, allow_nan=False) + "\n")


def run_atlas(
    pairs: Iterable[PairAtlasInput], *, out_dir: Path | None = None, **kwargs: object
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the output layer for supplied rolling results and optionally persist it."""
    tables = [summarize_pair(pair, **kwargs) for pair in pairs]
    pair_table = pd.concat([x[0] for x in tables], ignore_index=True)
    station_table = pd.concat([x[1] for x in tables], ignore_index=True)
    bootstrap_table = pd.concat([x[2] for x in tables], ignore_index=True)
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        pair_table.to_parquet(out_dir / "pairs.parquet", index=False)
        station_table.to_parquet(out_dir / "stations.parquet", index=False)
        bootstrap_table.to_parquet(out_dir / "bootstrap.parquet", index=False)
    return pair_table, station_table, bootstrap_table
