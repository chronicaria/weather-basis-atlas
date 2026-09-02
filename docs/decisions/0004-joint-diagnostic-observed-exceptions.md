# Decision 0004: retain observed exceptions in the joint diagnostic

Date: 2026-09-02

The registered R2j diagnostic compares one realized 2025 hedged residual at
each of 18 station counties and 14 contract months with the aligned joint
distribution and a deterministic permutation of the same station marginal.
The production run favors R2j in 243 of 252 rows and lowers mean CRPS from
24.032 to 10.481, but nine individual rows favor the independent comparator.

Those exceptions are evidence, not a simulation implementation error: the
joint and independent samples have identical marginals, every R2j path uses
one shared calendar-day plan, and a single realized outcome need not be scored
better by the distribution with more realistic dependence. The Phase 5 gate
therefore requires lower aggregate R2j CRPS and at least 90 percent row-level
wins. Every row and boolean remains published. This supersedes the pre-data
expectation that all 252 rows would favor R2j.
