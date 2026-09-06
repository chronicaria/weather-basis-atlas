"""Project frozen R01 evidence into explicit public decision records."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd


def build_atlas_public_rows(
    root: Path, r01_dir: Path, *, modeled_station_ids=None, valuation_date=date(2026, 7, 1)
) -> Iterator[dict[str, object]]:
    """Yield one V2 public row per county/pair, preserving decision/evaluation identity."""
    from weather_basis.hedge.asof import current_pair

    comparisons = pd.read_parquet(r01_dir / "matched_comparisons.parquet")
    intervals = pd.read_parquet(r01_dir / "r01_uncertainty_stability.parquet").set_index(
        ["pair", "fips"]
    )
    all_station_rows = pd.read_parquet(root / "results/atlas/stations.parquet")
    all_station_rows["fips"] = all_station_rows.fips.astype(str).str.zfill(5)
    registry = pd.read_csv(root / "data/metadata/station_registry.csv").iloc[:13]
    names = dict(zip(registry.ghcnd_id.astype(str), registry.name.astype(str), strict=True))
    station_ids = registry.ghcnd_id.astype(str).to_numpy()
    for comparison_path in sorted((r01_dir / "policy_decisions").glob("*.parquet")):
        pair = comparison_path.stem
        matched = comparisons.loc[comparisons.pair.eq(pair)].set_index("fips")
        station_groups = {
            fips: group.sort_values("distance_km")
            for fips, group in all_station_rows.loc[all_station_rows.pair.eq(pair)].groupby("fips")
        }
        current_decisions = current_pair(
            root, pair, valuation_date=valuation_date, modeled_station_ids=modeled_station_ids
        )
        for fips, evidence in matched.iterrows():
            fips = str(fips).zfill(5)
            uncertainty = intervals.loc[(pair, fips)]
            selection = current_decisions[fips]
            chosen = next(
                (i for i, value in enumerate(station_ids) if value == selection["station_id"]), -1
            )
            candidates = station_groups[fips]
            alternatives = [
                {
                    "station_id": str(item.station),
                    "station_name": names.get(str(item.station), str(item.station)),
                    "distance_km": float(item.distance_km),
                    "historical_he": float(item.he_pooled) if np.isfinite(item.he_pooled) else None,
                    "n_test": int(item.n_test),
                    "metric_definition": "V1 pooled HE on variable support; not matched policy HE",
                }
                for item in candidates.itertuples(index=False)
            ]
            status = "evaluable" if evidence.reason == "ok" else "unavailable"
            current = (
                "eligible_modeled_proxy"
                if chosen >= 0 and modeled_station_ids is not None
                else "unavailable_aligned_station_model"
            )
            yield {
                "fips": fips,
                "pair": pair,
                "historical_evidence": {"status": status, "reason_code": str(evidence.reason)},
                "current_availability": {
                    "status": current,
                    "reason_code": selection["reason_code"]
                    if modeled_station_ids is not None
                    else "scenario_model_not_yet_accepted",
                },
                "selection_asof": selection,
                "matched_policy": {
                    "comparison_id": f"r01:{pair}:{fips}",
                    "policy_id": "prior_best",
                    "n_common": int(evidence.n_common),
                    "metric": {
                        "value": float(evidence.he_prior_best)
                        if np.isfinite(evidence.he_prior_best)
                        else None,
                        "units": "ratio",
                        "definition": "D06 replication-MSE HE",
                    },
                    "nearest_he": float(evidence.he_nearest)
                    if np.isfinite(evidence.he_nearest)
                    else None,
                    "delta_he": float(evidence.he_prior_best - evidence.he_nearest)
                    if np.isfinite(evidence.he_prior_best) and np.isfinite(evidence.he_nearest)
                    else None,
                    "common_seasons": list(evidence.season_ids),
                    "interval": {
                        "low": float(uncertainty.interval_low)
                        if np.isfinite(uncertainty.interval_low)
                        else None,
                        "high": float(uncertainty.interval_high)
                        if np.isfinite(uncertainty.interval_high)
                        else None,
                        "method": str(uncertainty.interval_method),
                        "block_length": int(uncertainty.block_length),
                        "n_blocks": int(uncertainty.n_blocks),
                    },
                    "selection_stability": float(uncertainty.selection_stability)
                    if np.isfinite(uncertainty.selection_stability)
                    else None,
                    "coverage": int(evidence.n_common) / 45,
                    "n_excluded_prior_best": int(evidence.n_excluded_prior_best),
                    "n_excluded_nearest": int(evidence.n_excluded_nearest),
                    "reason_code": str(evidence.reason),
                },
                "alternatives": alternatives,
            }
