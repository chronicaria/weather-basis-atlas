"""Bounded-memory reconstruction of the V2 national R01 policy panel.

This reuses rolling tensors only after rebuilding their decision eligibility
from retained station support metadata.  It never treats a finite held-out
residual as a decision-time availability signal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from weather_basis.hedge.evaluation import coverage_summary, evaluate_policy, matched_comparison
from weather_basis.hedge.policies import PolicyDecisions, choose_policy


@dataclass(frozen=True)
class NationalReconstruction:
    decisions: pd.DataFrame
    evaluations: pd.DataFrame
    comparisons: pd.DataFrame
    coverage: pd.DataFrame
    tensor_adequacy: pd.DataFrame


def tensor_adequacy(root: Path, pair: str) -> dict[str, object]:
    """Report whether retained arrays permit causal reconstruction, not relabelling."""
    tensor = root / "results" / "atlas" / "tensors" / f"{pair}.npz"
    if not tensor.is_file():
        return {"pair": pair, "adequate": False, "reason": "missing_rolling_tensor"}
    with np.load(tensor) as archive:
        required = {"alpha", "h", "resid", "seasons", "train_r2"}
        missing = sorted(required - set(archive.files))
        if missing:
            return {"pair": pair, "adequate": False, "reason": f"missing:{','.join(missing)}"}
    paths = [
        root / "results" / "indices" / f"county_{pair}.parquet",
        root / "data" / "metadata" / "station_registry.csv",
        root / "results" / "atlas" / "pairs.parquet",
    ]
    return {
        "pair": pair,
        "adequate": all(path.is_file() for path in paths),
        "reason": "reconstructable_from_tensor_plus_registered_support"
        if all(path.is_file() for path in paths)
        else "missing_retained_target_or_support_metadata",
    }


def _prior_scores(
    residual: np.ndarray,
    target: np.ndarray,
    train_r2: np.ndarray,
    eligible: np.ndarray,
    *,
    trailing: int,
    min_oos: int,
) -> np.ndarray:
    """Prior-only trailing HE, with train R² before any station reaches support."""
    origins, exposures, stations = residual.shape
    score = np.full_like(residual, np.nan, dtype=float)
    for t in range(origins):
        history_ready = np.zeros(exposures, dtype=bool)
        history_score = np.full((exposures, stations), np.nan)
        for c in range(exposures):
            for j in range(stations):
                usable = (
                    eligible[:t, c, j]
                    & np.isfinite(residual[:t, c, j])
                    & np.isfinite(target[:t, c])
                )
                index = np.flatnonzero(usable)
                if index.size >= min_oos:
                    index = index[-trailing:]
                    values, target_values = residual[index, c, j], target[index, c]
                    denom = np.sum((target_values - target_values.mean()) ** 2)
                    tolerance = max(
                        np.finfo(float).eps, 1e-12 * max(float(target_values @ target_values), 1.0)
                    )
                    if denom > tolerance:
                        history_score[c, j] = 1.0 - np.sum(values * values) / denom
                        history_ready[c] = True
        for c in range(exposures):
            score[t, c] = history_score[c] if history_ready[c] else train_r2[t, c]
    return score


def _choices_frame(
    pair: str, fips: np.ndarray, seasons: np.ndarray, decision: PolicyDecisions
) -> pd.DataFrame:
    origins, exposures = decision.choice.shape
    return pd.DataFrame(
        {
            "pair": pair,
            "season": np.repeat(seasons, exposures),
            "fips": np.tile(fips.astype(str), origins),
            "policy": decision.policy,
            "choice_station_index": decision.choice.reshape(-1),
            "decision_reason": decision.reason.reshape(-1),
            "decision_eligible": np.take_along_axis(
                decision.eligible, np.maximum(decision.choice, 0)[..., None], axis=2
            ).reshape(-1)
            & (decision.choice.reshape(-1) >= 0),
        }
    )


def reconstruct_pair(
    root: Path,
    pair: str,
    *,
    trailing: int = 10,
    min_oos: int = 5,
    last_test_year: int = 2025,
) -> NationalReconstruction:
    """Reconstruct nearest and prior-best panels for one pair from retained inputs."""
    adequacy = tensor_adequacy(root, pair)
    if not adequacy["adequate"]:
        raise ValueError(f"{pair}: {adequacy['reason']}")
    registry = pd.read_csv(root / "data/metadata/station_registry.csv").iloc[:13]
    station_ids = registry.ghcnd_id.astype(str).to_numpy()
    panel_station_ids = np.load(root / "data/panel/station_ids.npy").astype(str)[:13]
    if not np.array_equal(station_ids, panel_station_ids):
        raise ValueError("Retained tensor station axis differs from frozen panel registry order")
    first_test = registry.first_test_season.to_numpy()
    with np.load(root / "results" / "atlas" / "tensors" / f"{pair}.npz") as archive:
        seasons = archive["seasons"].copy()
        residual = archive["resid"].astype(float)
        train_r2 = archive["train_r2"].astype(float)
        prior_fit = np.isfinite(archive["alpha"]) & np.isfinite(archive["h"])
    within = seasons <= last_test_year
    seasons, residual, train_r2, prior_fit = (
        seasons[within],
        residual[within],
        train_r2[within],
        prior_fit[within],
    )
    county = pd.read_parquet(root / "results" / "indices" / f"county_{pair}.parquet")
    fips = np.sort(county.fips.astype(str).str.zfill(5).unique())
    if not np.array_equal(fips, np.load(root / "data/panel/fips.npy").astype(str)):
        raise ValueError("Retained tensor county axis differs from frozen panel FIPS order")
    target = (
        county.assign(fips=county.fips.astype(str).str.zfill(5))
        .pivot(index="season", columns="fips", values="anomaly")
        .reindex(index=seasons, columns=fips)
        .to_numpy(dtype=float)
    )
    if residual.shape[:2] != target.shape:
        raise ValueError(f"{pair}: tensor and retained county target dimensions disagree")
    pairs = pd.read_parquet(root / "results" / "atlas" / "pairs.parquet")
    nearest_ids = pairs.loc[pairs.pair.eq(pair)].set_index("fips").reindex(fips).station_nearest
    lookup = {station: j for j, station in enumerate(station_ids)}
    nearest = nearest_ids.map(lookup).to_numpy(dtype=np.intp)
    if np.any(nearest < 0):
        raise ValueError(f"{pair}: unknown nearest station in retained pairs table")
    # Registered availability is a pre-outcome rule. Training support is still
    # represented by finite prior-only scores, never by the current residual.
    eligible = (
        np.broadcast_to(seasons[:, None, None] >= first_test[None, None, :], residual.shape)
        & prior_fit
    )
    distances = pd.read_parquet(root / "results/atlas/stations.parquet")
    distance_matrix = (
        distances.loc[distances.pair.eq(pair)]
        .pivot(index="fips", columns="station", values="distance_km")
        .reindex(index=fips, columns=station_ids)
        .to_numpy(dtype=float)
    )
    if not np.isfinite(distance_matrix).all():
        raise ValueError("Incomplete geographical candidate ranking")
    rankings = np.argsort(distance_matrix, axis=1, kind="stable")
    scores = _prior_scores(residual, target, train_r2, eligible, trailing=trailing, min_oos=min_oos)
    nearest_decision = choose_policy(
        "nearest_eligible",
        decision_eligible=eligible,
        prior_scores=scores,
        nearest_station=nearest,
        candidate_rankings=rankings,
    )
    best_decision = choose_policy(
        "prior_best",
        decision_eligible=eligible,
        prior_scores=scores,
        nearest_station=nearest,
        candidate_rankings=rankings,
    )
    scoreable = np.isfinite(residual) & np.isfinite(target)[..., None]
    nearest_eval = evaluate_policy(
        nearest_decision,
        target=target,
        residual_by_station=residual,
        evaluation_scoreable=scoreable,
        season_ids=seasons,
    )
    best_eval = evaluate_policy(
        best_decision,
        target=target,
        residual_by_station=residual,
        evaluation_scoreable=scoreable,
        season_ids=seasons,
    )
    comparison = matched_comparison(best_eval, nearest_eval, target)
    decisions = pd.concat(
        [
            _choices_frame(pair, fips, seasons, nearest_decision),
            _choices_frame(pair, fips, seasons, best_decision),
        ],
        ignore_index=True,
    )
    evaluations = pd.concat(
        [
            decisions.loc[decisions.policy.eq(nearest_eval.policy)].assign(
                residual=nearest_eval.residual.reshape(-1),
                scoreable=nearest_eval.scoreable.reshape(-1),
                evaluation_reason=nearest_eval.reason.reshape(-1),
            ),
            decisions.loc[decisions.policy.eq(best_eval.policy)].assign(
                residual=best_eval.residual.reshape(-1),
                scoreable=best_eval.scoreable.reshape(-1),
                evaluation_reason=best_eval.reason.reshape(-1),
            ),
        ],
        ignore_index=True,
    )
    comparison_frame = pd.DataFrame(
        {
            "pair": pair,
            "fips": fips,
            "n_common": comparison.n_common,
            "n_excluded_prior_best": comparison.n_excluded_left,
            "n_excluded_nearest": comparison.n_excluded_right,
            "denominator": comparison.denominator,
            "he_prior_best": comparison.left_he,
            "he_nearest": comparison.right_he,
            # The generic comparison is right-minus-left improvement; this
            # exported field explicitly names loss(prior)-loss(nearest).
            "paired_loss_change_prior_minus_nearest": -comparison.paired_squared_loss_change,
            "reason": comparison.reason,
            "season_ids": [list(value) for value in comparison.season_ids],
        }
    )
    evaluated = comparison.reason == "ok"
    coverage = coverage_summary(evaluated, comparison.left_he >= comparison.right_he)
    coverage_frame = pd.DataFrame([{"pair": pair, **coverage.__dict__}])
    return NationalReconstruction(
        decisions, evaluations, comparison_frame, coverage_frame, pd.DataFrame([adequacy])
    )


def reconstruct_national(
    root: Path, *, pairs: tuple[str, ...] | None = None, out_dir: Path | None = None
) -> NationalReconstruction:
    """Run declared pairs serially and partition large policy panels.

    When ``out_dir`` is set, national decision/evaluation panels are written
    one pair at a time; their returned frames are empty to preserve the memory
    bound. The partition directories are the artifact contract.
    """
    selected = pairs or tuple(
        sorted(path.stem for path in (root / "results/atlas/tensors").glob("*.npz"))
    )
    built: list[NationalReconstruction] = []
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "policy_decisions").mkdir(exist_ok=True)
        (out_dir / "policy_evaluations").mkdir(exist_ok=True)
        for pair in selected:
            item = reconstruct_pair(root, pair)
            item.decisions.to_parquet(out_dir / "policy_decisions" / f"{pair}.parquet", index=False)
            item.evaluations.to_parquet(
                out_dir / "policy_evaluations" / f"{pair}.parquet", index=False
            )
            built.append(
                NationalReconstruction(
                    pd.DataFrame(),
                    pd.DataFrame(),
                    item.comparisons,
                    item.coverage,
                    item.tensor_adequacy,
                )
            )
    else:
        built = [reconstruct_pair(root, pair) for pair in selected]
    result = NationalReconstruction(
        pd.concat([item.decisions for item in built], ignore_index=True),
        pd.concat([item.evaluations for item in built], ignore_index=True),
        pd.concat([item.comparisons for item in built], ignore_index=True),
        pd.concat([item.coverage for item in built], ignore_index=True),
        pd.concat([item.tensor_adequacy for item in built], ignore_index=True),
    )
    if out_dir is not None:
        result.comparisons.to_parquet(out_dir / "matched_comparisons.parquet", index=False)
        result.coverage.to_parquet(out_dir / "coverage.parquet", index=False)
        result.tensor_adequacy.to_parquet(out_dir / "tensor_adequacy.parquet", index=False)
        (out_dir / "r01_protocol.json").write_text(json.dumps(R01_PROTOCOL, indent=2) + "\n")
    return result


R01_PROTOCOL = {
    "id": "R01",
    "question": "Does corrected prior-score selection beat nearest on matched seasons?",
    "baseline": "nearest_eligible",
    "challenger": "prior_best",
    "metric": "D06 replication-MSE HE",
    "common_support": "exact paired seasons",
    "equivalence_bands": [0.0, 0.02, 0.05],
    "inference_unit": "chronological outer origin/season",
    "status": "registered_before_reconstruction",
}
