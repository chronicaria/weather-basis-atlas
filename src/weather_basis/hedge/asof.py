"""New current decisions from an explicitly cut historical score tape."""

from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from weather_basis.contracts.calendar import Pair
from weather_basis.contracts.registry import load_contract_registry
from weather_basis.hedge.policies import choose_policy
from weather_basis.provenance.ids import content_id, file_sha256


def choose_from_score_tape(
    *,
    residuals,
    targets,
    seasons,
    station_ids,
    fips,
    distances,
    valuation_date,
    month,
    first_test,
    min_oos=5,
    trailing=10,
    modeled_station_ids=None,
):
    """Only completed observations before valuation may enter the current score.

    This calculates a fresh final score from historical residuals; it never
    copies the last historical decision (which excluded that season's outcome).
    """
    ends = np.asarray(
        [date(int(year), month, calendar.monthrange(int(year), month)[1]) for year in seasons],
        dtype=object,
    )
    prior = ends < valuation_date
    scores = np.full(residuals.shape[1:], np.nan)
    counts = np.zeros(scores.shape, dtype=int)
    last_observed = np.full(scores.shape, -1, dtype=int)
    for c, j in np.ndindex(scores.shape):
        usable = prior & (seasons >= first_test[j]) & np.isfinite(residuals[:, c, j])
        usable &= np.isfinite(targets[:, c])
        rows = np.flatnonzero(usable)[-trailing:]
        counts[c, j] = len(rows)
        if len(rows):
            last_observed[c, j] = seasons[rows[-1]]
        if len(rows) >= min_oos:
            y, r = targets[rows, c], residuals[rows, c, j]
            denominator = float(np.sum((y - y.mean()) ** 2))
            if denominator > 1e-12 * max(float(y @ y), 1.0):
                scores[c, j] = 1.0 - float(r @ r) / denominator
    eligible = np.isfinite(scores)
    if modeled_station_ids is not None:
        eligible &= np.isin(station_ids, tuple(modeled_station_ids))[None, :]
    rankings = np.argsort(distances, axis=1, kind="stable")
    decisions = choose_policy(
        "prior_best",
        decision_eligible=eligible[None],
        prior_scores=scores[None],
        nearest_station=rankings[:, 0],
        candidate_rankings=rankings,
    )
    return decisions, scores, counts, last_observed


def current_pair(
    root: Path,
    pair: str,
    *,
    valuation_date: date = date(2026, 7, 1),
    modeled_station_ids: tuple[str, ...] | None = None,
):
    registry = pd.read_csv(root / "data/metadata/station_registry.csv").iloc[:13]
    station_ids = registry.ghcnd_id.astype(str).to_numpy()
    if not np.array_equal(
        station_ids, np.load(root / "data/panel/station_ids.npy").astype(str)[:13]
    ):
        raise ValueError("Current score tape has inconsistent station axis")
    tensor_path = root / f"results/atlas/tensors/{pair}.npz"
    with np.load(tensor_path) as tensors:
        residuals, seasons = tensors["resid"].astype(float), tensors["seasons"]
    county = pd.read_parquet(root / f"results/indices/county_{pair}.parquet")
    fips = np.load(root / "data/panel/fips.npy").astype(str)
    targets = (
        county.pivot(index="season", columns="fips", values="anomaly")
        .reindex(index=seasons, columns=fips)
        .to_numpy(dtype=float)
    )
    stations = pd.read_parquet(root / "results/atlas/stations.parquet")
    distances = (
        stations.loc[stations.pair.eq(pair)]
        .pivot(index="fips", columns="station", values="distance_km")
        .reindex(index=fips, columns=station_ids)
        .to_numpy(dtype=float)
    )
    if not np.isfinite(distances).all():
        raise ValueError("Incomplete current station distance support")
    index, month = pair.split("-")
    window = load_contract_registry(root).contract_window(Pair(index, int(month)), valuation_date)
    choice, scores, counts, last = choose_from_score_tape(
        residuals=residuals,
        targets=targets,
        seasons=seasons,
        station_ids=station_ids,
        fips=fips,
        distances=distances,
        valuation_date=valuation_date,
        month=int(month),
        first_test=registry.first_test_season.to_numpy(),
        modeled_station_ids=modeled_station_ids,
    )
    tape_hash = file_sha256(tensor_path)
    rows = {}
    for c, county_id in enumerate(fips):
        selected = int(choice.choice[0, c])
        data = {
            "valuation_date": str(valuation_date),
            "contract_window_id": window.contract_window_id,
            "contract_year": window.contract_year,
            "observation_start": window.observation_start,
            "observation_end": window.observation_end,
            "score_tape_id": tape_hash,
            "policy_id": "prior_best-asof-score-tape-v1",
            "fips": county_id,
            "pair": pair,
            "scores": [float(v) if np.isfinite(v) else None for v in scores[c]],
            "score_counts": counts[c].tolist(),
            "eligible_station_ids": station_ids[choice.eligible[0, c]].tolist(),
            "reason_code": str(choice.reason[0, c]),
            "station_id": str(station_ids[selected]) if selected >= 0 else None,
        }
        if selected >= 0:
            year = int(last[c, selected])
            data.update(
                station_name=str(registry.iloc[selected]["name"]),
                observation_cutoff=str(
                    date(year, int(month), calendar.monthrange(year, int(month))[1])
                ),
                metadata_cutoff="2026-09-02 (retrospective frozen metadata)",
                decision_time=str(valuation_date),
                score=float(scores[c, selected]),
            )
        data["selection_id"] = content_id(data, prefix="selection")
        rows[county_id] = data
    return rows
