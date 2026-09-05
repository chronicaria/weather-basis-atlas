"""B05 hand cases for causal, matched V2 policy evaluation."""

from __future__ import annotations

import numpy as np
import pytest

from weather_basis.hedge.evaluation import (
    coverage_summary,
    evaluate_policy,
    matched_comparison,
    selection_stability,
)
from weather_basis.hedge.policies import choose_policy
from weather_basis.hedge.selection import point_in_time_best


def test_held_out_station_outcome_cannot_change_frozen_choice() -> None:
    eligible = np.ones((3, 1, 2), dtype=bool)
    scores = np.array([[[0.1, 0.9]], [[0.1, 0.9]], [[0.1, 0.9]]])
    before = choose_policy(
        "prior_best", decision_eligible=eligible, prior_scores=scores, nearest_station=np.array([0])
    )
    residual = np.array([[[1.0, 0.2]], [[1.0, 0.2]], [[1.0, 0.2]]])
    target = np.array([[1.0], [2.0], [3.0]])
    baseline = evaluate_policy(
        before,
        target=target,
        residual_by_station=residual,
        evaluation_scoreable=np.ones_like(residual, dtype=bool),
    )
    changed = residual.copy()
    changed[2, 0, 1] = np.nan
    after = evaluate_policy(
        before,
        target=target,
        residual_by_station=changed,
        evaluation_scoreable=np.isfinite(changed),
    )
    assert before.choice.tolist() == [[1], [1], [1]]
    assert np.array_equal(baseline.choice, after.choice)
    assert after.reason[2, 0] == "missing_realized_score"


def test_point_in_time_selection_does_not_read_current_residual_availability() -> None:
    residual = np.array([[[0.0, 0.0]], [[0.0, np.nan]]])
    target = np.array([[1.0], [2.0]])
    r2 = np.array([[[0.1, 0.9]], [[0.1, 0.9]]])
    selected = point_in_time_best(residual, target, r2, np.array([2000, 2000]), min_oos=2)
    assert selected[1, 0] == 1


def test_matched_he_uses_exact_common_support_and_paired_loss() -> None:
    scores = np.array([[[0.1, 0.9]]] * 4)
    eligible = np.ones((4, 1, 2), dtype=bool)
    left = choose_policy(
        "nearest_eligible",
        decision_eligible=eligible,
        prior_scores=scores,
        nearest_station=np.array([0]),
    )
    right = choose_policy(
        "prior_best", decision_eligible=eligible, prior_scores=scores, nearest_station=np.array([0])
    )
    target = np.array([[0.0], [2.0], [4.0], [6.0]])
    residuals = np.array([[[1.0, 0.5]], [[1.0, 0.5]], [[1.0, np.nan]], [[1.0, 0.5]]])
    l_eval = evaluate_policy(
        left,
        target=target,
        residual_by_station=residuals,
        evaluation_scoreable=np.isfinite(residuals),
        season_ids=np.array([10, 11, 12, 13]),
    )
    r_eval = evaluate_policy(
        right,
        target=target,
        residual_by_station=residuals,
        evaluation_scoreable=np.isfinite(residuals),
        season_ids=np.array([10, 11, 12, 13]),
    )
    comparison = matched_comparison(l_eval, r_eval, target)
    assert comparison.season_ids == ((10, 11, 13),)
    assert comparison.n_common.tolist() == [3]
    assert comparison.n_excluded_left.tolist() == [0]
    assert comparison.n_excluded_right.tolist() == [1]
    assert comparison.denominator[0] == pytest.approx(56 / 3)
    assert comparison.left_he[0] == pytest.approx(1 - 3 / (56 / 3))
    assert comparison.right_he[0] == pytest.approx(1 - 0.75 / (56 / 3))
    # The reported change is right minus left, so a better right policy is negative.
    assert comparison.paired_squared_loss_change[0] == pytest.approx(-2.25)


def test_v2_degenerate_target_is_unavailable_and_coverage_is_separate() -> None:
    eligible = np.ones((2, 1, 1), dtype=bool)
    choice = choose_policy(
        "nearest_eligible",
        decision_eligible=eligible,
        prior_scores=np.zeros_like(eligible, dtype=float),
        nearest_station=np.array([0]),
    )
    evaluation = evaluate_policy(
        choice,
        target=np.array([[3.0], [3.0]]),
        residual_by_station=np.zeros((2, 1, 1)),
        evaluation_scoreable=np.ones((2, 1, 1), dtype=bool),
    )
    compared = matched_comparison(evaluation, evaluation, np.array([[3.0], [3.0]]))
    assert compared.reason.tolist() == ["degenerate_target"]
    assert np.isnan(compared.left_he[0])
    coverage = coverage_summary(
        np.array([True, True, False]),
        np.array([True, False, False]),
        weights=np.array([2.0, 1.0, 7.0]),
    )
    assert (coverage.evaluated, coverage.failed, coverage.unavailable) == (2, 1, 1)
    assert coverage.coverage == pytest.approx(2 / 3)
    assert coverage.failure_rate_evaluated == pytest.approx(1 / 2)
    assert coverage.weighted_coverage == pytest.approx(0.3)


def test_policy_ties_fallback_and_stability_are_deterministic() -> None:
    eligible = np.array([[[False, True, True]], [[True, True, True]], [[True, True, True]]])
    scores = np.array([[[np.nan, np.nan, np.nan]], [[0.4, 0.4, 0.2]], [[0.4, 0.3, 0.2]]])
    decisions = choose_policy(
        "prior_best", decision_eligible=eligible, prior_scores=scores, nearest_station=np.array([0])
    )
    assert decisions.choice[:, 0].tolist() == [1, 0, 0]
    assert decisions.reason[:, 0].tolist() == [
        "fallback_lowest_station_index",
        "selected",
        "selected",
    ]
    assert selection_stability(decisions.choice).tolist() == [pytest.approx(2 / 3)]
    assert not decisions.choice.flags.writeable


def test_nearest_eligible_uses_declared_geographic_ranking_for_fallback() -> None:
    eligible = np.array([[[False, True, True]]])
    policy = choose_policy(
        "nearest_eligible",
        decision_eligible=eligible,
        prior_scores=np.zeros_like(eligible, dtype=float),
        nearest_station=np.array([0]),
        candidate_rankings=np.array([[0, 2, 1]]),
    )
    assert policy.choice.tolist() == [[2]]
    assert policy.reason.tolist() == [["fallback_nearest_eligible"]]
