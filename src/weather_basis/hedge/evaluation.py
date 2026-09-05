"""Matched, post-outcome policy evaluation for V2 (D06/D07)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from weather_basis.hedge.policies import PolicyDecisions


@dataclass(frozen=True)
class PolicyEvaluation:
    policy: str
    choice: np.ndarray
    residual: np.ndarray
    scoreable: np.ndarray
    reason: np.ndarray
    season_ids: np.ndarray


@dataclass(frozen=True)
class MatchedComparison:
    left_policy: str
    right_policy: str
    season_ids: tuple[tuple[object, ...], ...]
    n_common: np.ndarray
    n_excluded_left: np.ndarray
    n_excluded_right: np.ndarray
    denominator: np.ndarray
    left_he: np.ndarray
    right_he: np.ndarray
    paired_squared_loss_change: np.ndarray
    reason: np.ndarray


@dataclass(frozen=True)
class CoverageSummary:
    total: int
    evaluated: int
    passed: int
    failed: int
    unavailable: int
    coverage: float
    failure_rate_evaluated: float
    weighted_coverage: float | None


def evaluate_policy(
    decisions: PolicyDecisions,
    *,
    target: np.ndarray,
    residual_by_station: np.ndarray,
    evaluation_scoreable: np.ndarray,
    season_ids: np.ndarray | None = None,
) -> PolicyEvaluation:
    """Score frozen choices later; missing outcomes never trigger reselection."""
    target_array, residuals = (
        np.asarray(target, dtype=float),
        np.asarray(residual_by_station, dtype=float),
    )
    scoreable = np.asarray(evaluation_scoreable, dtype=bool)
    if (
        residuals.ndim != 3
        or target_array.shape != residuals.shape[:2]
        or scoreable.shape != residuals.shape
    ):
        raise ValueError(
            "target, residual_by_station, and evaluation_scoreable shapes are incompatible"
        )
    if decisions.choice.shape != target_array.shape:
        raise ValueError("decision choice shape must match target")
    seasons = np.arange(target_array.shape[0]) if season_ids is None else np.asarray(season_ids)
    if seasons.shape != (target_array.shape[0],):
        raise ValueError("season_ids must have one entry per origin")
    residual = np.full(target_array.shape, np.nan)
    evaluated = np.zeros(target_array.shape, dtype=bool)
    reason = np.full(target_array.shape, "missing_realized_score", dtype="U32")
    for t, c in np.ndindex(target_array.shape):
        station = int(decisions.choice[t, c])
        if station < 0:
            reason[t, c] = str(decisions.reason[t, c])
        elif (
            scoreable[t, c, station]
            and np.isfinite(target_array[t, c])
            and np.isfinite(residuals[t, c, station])
        ):
            residual[t, c], evaluated[t, c], reason[t, c] = (
                residuals[t, c, station],
                True,
                "scoreable",
            )
    return PolicyEvaluation(
        decisions.policy, decisions.choice.copy(), residual, evaluated, reason, seasons.copy()
    )


def _v2_he(residual: np.ndarray, target: np.ndarray) -> tuple[float, float, str]:
    if residual.size < 2:
        return np.nan, np.nan, "insufficient_common_support"
    centered = target - target.mean()
    denominator = float(centered @ centered)
    tolerance = max(np.finfo(float).eps, 1.0e-12 * max(float(target @ target), 1.0))
    if denominator <= tolerance:
        return np.nan, denominator, "degenerate_target"
    return float(1.0 - (residual @ residual) / denominator), denominator, "ok"


def matched_comparison(
    left: PolicyEvaluation, right: PolicyEvaluation, target: np.ndarray
) -> MatchedComparison:
    """D06 common-support HE plus paired squared-loss improvement."""
    values = np.asarray(target, dtype=float)
    if left.residual.shape != right.residual.shape or values.shape != left.residual.shape:
        raise ValueError("left, right, and target shapes must agree")
    if not np.array_equal(left.season_ids, right.season_ids):
        raise ValueError("comparisons require identical season ids")
    n = values.shape[1]
    common_n, exclude_l, exclude_r = (np.zeros(n, dtype=np.intp) for _ in range(3))
    denominator = np.full(n, np.nan)
    left_he = np.full(n, np.nan)
    right_he = np.full(n, np.nan)
    paired = np.full(n, np.nan)
    reasons = np.full(n, "insufficient_common_support", dtype="U32")
    groups: list[tuple[object, ...]] = []
    for c in range(n):
        l_ok = left.scoreable[:, c] & np.isfinite(left.residual[:, c]) & np.isfinite(values[:, c])
        r_ok = right.scoreable[:, c] & np.isfinite(right.residual[:, c]) & np.isfinite(values[:, c])
        common = l_ok & r_ok
        common_n[c], exclude_l[c], exclude_r[c] = (
            common.sum(),
            (r_ok & ~l_ok).sum(),
            (l_ok & ~r_ok).sum(),
        )
        groups.append(tuple(left.season_ids[common].tolist()))
        if common.any():
            lres, rres, target_common = (
                left.residual[common, c],
                right.residual[common, c],
                values[common, c],
            )
            left_he[c], denominator[c], reasons[c] = _v2_he(lres, target_common)
            right_he[c], right_denominator, right_reason = _v2_he(rres, target_common)
            if (
                not np.isclose(denominator[c], right_denominator, equal_nan=True)
                or right_reason != reasons[c]
            ):
                raise RuntimeError("common-support metrics disagree")
            if reasons[c] == "ok":
                paired[c] = float(np.sum(rres * rres - lres * lres))
    return MatchedComparison(
        left.policy,
        right.policy,
        tuple(groups),
        common_n,
        exclude_l,
        exclude_r,
        denominator,
        left_he,
        right_he,
        paired,
        reasons,
    )


def coverage_summary(
    evaluated: np.ndarray, passed: np.ndarray, *, weights: np.ndarray | None = None
) -> CoverageSummary:
    """Score coverage and evaluated failures have separate denominators."""
    mask, success = np.asarray(evaluated, dtype=bool), np.asarray(passed, dtype=bool)
    if mask.shape != success.shape:
        raise ValueError("evaluated and passed must have the same shape")
    total, count = mask.size, int(mask.sum())
    passed_count = int((mask & success).sum())
    weighted: float | None = None
    if weights is not None:
        w = np.asarray(weights, dtype=float)
        if w.shape != mask.shape:
            raise ValueError("weights must match evaluated")
        weighted = float(np.sum(w * mask) / np.sum(w)) if np.sum(w) > 0 else np.nan
    return CoverageSummary(
        total,
        count,
        passed_count,
        count - passed_count,
        total - count,
        count / total if total else np.nan,
        (count - passed_count) / count if count else np.nan,
        weighted,
    )


def selection_stability(choices: np.ndarray) -> np.ndarray:
    """Modal selected-station share across origins, excluding no-decisions."""
    values = np.asarray(choices, dtype=np.intp)
    if values.ndim != 2:
        raise ValueError("choices must have shape (origins, exposures)")
    answer = np.full(values.shape[1], np.nan)
    for c in range(values.shape[1]):
        selected = values[:, c][values[:, c] >= 0]
        if selected.size:
            answer[c] = np.bincount(selected).max() / selected.size
    return answer
