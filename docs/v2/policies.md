# V2 hedge policy evaluation

`choose_policy` freezes a station choice from `decision_eligible` and pre-origin
scores only. It has deterministic lowest-index ties and a recorded nearest-
eligible fallback. A missing realized station observation can make the later
`evaluate_policy` row unscoreable, but cannot change its choice.

`matched_comparison` scores two frozen panels only on their exact common season
IDs. V2 replication-MSE hedge effectiveness is
`1 - sum(residual^2) / sum((target - mean(common target))^2)`. The residual is
not recentered. The artifact retains common support, exclusions, denominator,
paired squared-loss change (right policy minus left policy, so negative favors
the right policy) and an unavailable reason. Near-zero target variation
is `degenerate_target`, not V1's 0/1 compatibility convention.

`coverage_summary` reports evaluated coverage separately from failures among
evaluated records; population weights, when supplied, are only geographic
coverage weights. `selection_stability` reports the modal selected-station share
across origins and is descriptive, not an independent-year confidence claim.
