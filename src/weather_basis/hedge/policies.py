"""Frozen pre-outcome hedge-policy decisions for V2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

PolicyName = Literal["nearest_eligible", "prior_best"]


@dataclass(frozen=True)
class PolicyDecisions:
    """One immutable station choice for each origin and exposure.

    ``choice`` is ``-1`` for a legitimate no-decision. Eligibility and scores
    are retained as audit traces and must be known before the outcome.
    """

    policy: str
    choice: np.ndarray
    eligible: np.ndarray
    score: np.ndarray
    reason: np.ndarray


NO_ELIGIBLE = "no_eligible_candidate"
SELECTED = "selected"
FALLBACK_NEAREST = "fallback_nearest_eligible"
FALLBACK_INDEX = "fallback_lowest_station_index"


def _frozen(array: np.ndarray) -> np.ndarray:
    """Copy an audit array and prevent mutation through the decision record."""
    result = np.array(array, copy=True)
    result.setflags(write=False)
    return result


def choose_policy(
    policy: PolicyName,
    *,
    decision_eligible: np.ndarray,
    prior_scores: np.ndarray,
    nearest_station: np.ndarray,
    candidate_rankings: np.ndarray | None = None,
) -> PolicyDecisions:
    """Freeze choices from decision eligibility and prior scores only.

    Ties resolve to the lowest station index. ``candidate_rankings`` should be
    supplied as ordered station indices (nearest first) for geographic nearest
    fallback.  Without it, fallback is explicitly lowest station index and is
    not a geographic nearest claim.
    """
    eligible = np.asarray(decision_eligible, dtype=bool)
    scores = np.asarray(prior_scores, dtype=float)
    nearest = np.asarray(nearest_station, dtype=np.intp)
    if eligible.ndim != 3:
        raise ValueError("decision_eligible must have shape (origins, exposures, stations)")
    if scores.shape != eligible.shape:
        raise ValueError("prior_scores must have the same shape as decision_eligible")
    if nearest.shape != (eligible.shape[1],):
        raise ValueError("nearest_station must have one entry per exposure")
    if np.any((nearest < 0) | (nearest >= eligible.shape[2])):
        raise ValueError("nearest_station contains an invalid station index")
    if candidate_rankings is None:
        rankings = np.broadcast_to(np.arange(eligible.shape[2]), eligible.shape[1:])
    else:
        rankings = np.asarray(candidate_rankings, dtype=np.intp)
        if rankings.shape != (eligible.shape[1], eligible.shape[2]):
            raise ValueError("candidate_rankings must have shape (exposures, stations)")
        expected = np.arange(eligible.shape[2])
        if not np.all(np.sort(rankings, axis=1) == expected):
            raise ValueError("every candidate ranking must contain every station exactly once")
    choice = np.full(eligible.shape[:2], -1, dtype=np.intp)
    reason = np.full(eligible.shape[:2], NO_ELIGIBLE, dtype="U32")
    for t, c in np.ndindex(choice.shape):
        candidates = eligible[t, c]
        if not candidates.any():
            continue
        near = int(nearest[c])
        fallback = int(rankings[c, np.flatnonzero(candidates[rankings[c]])[0]])
        fallback_reason = FALLBACK_NEAREST if candidate_rankings is not None else FALLBACK_INDEX
        if policy == "nearest_eligible":
            choice[t, c] = near if candidates[near] else fallback
            reason[t, c] = SELECTED if candidates[near] else fallback_reason
        elif policy == "prior_best":
            valid = candidates & np.isfinite(scores[t, c])
            if valid.any():
                choice[t, c], reason[t, c] = (
                    int(np.argmax(np.where(valid, scores[t, c], -np.inf))),
                    SELECTED,
                )
            else:
                choice[t, c] = near if candidates[near] else fallback
                reason[t, c] = fallback_reason
        else:
            raise ValueError(f"unknown policy: {policy}")
    return PolicyDecisions(
        policy, _frozen(choice), _frozen(eligible), _frozen(scores), _frozen(reason)
    )
