# B10 quote-batch validation

The calendar-aligned corrected R2j benchmark at
`var/r2j-production-7county-512/` was evaluated on all 98 county/pair inputs
(seven counties and fourteen pairs), using six call/put tickets per input and
512 common paths.  It uses the common May 31 observation cutoff and a 30-day
June bridge before the July horizon. Each selected
station came from the independent July 2026 as-of score tape and was resolved
by its exact station/pair entity in `stations_14pair.npz`.  All 98 selections
were present and finite; no county-self path was substituted.

For each county/pair, a 200-replicate annual burn-history multiplicity matrix
was created once and reused across the six compatible tickets.  The batched
kernel matched a direct ticket-by-ticket reference for expected payout,
payoff-specific hedge ratio, residual expected payout, and bootstrap model-load
standard error to exact float64 agreement.

The bounded implementation did not improve this deliberately tiny workload:
median time was 17.71 ms versus 10.80 ms for the direct reference across seven
repetitions (0.610x). This is retained as a measured limitation rather than a
performance claim.  The complete machine-readable record is
`results/v2/validation/b10-quote-batch-r2j-7county-512.json`.

The matched bounded second seed is retained at
`var/r2j-production-b10-second-seed-7county-512/`. The independent-seed
comparison passed all 2,940 checks across 98 selected county/pair scenarios
and 588 tickets at the fixed 4σ threshold. Its declared seed IDs are
`r2j-production-bridged-v2-20260905` and
`r2j-production-bridged-v2-20260906`.

The prior failed report is retained as
`results/v2/validation/b10-independent-seed-r2j-7county-512-pre-estimator-se-fix.json`.
It incorrectly used residual dispersion for a same-sample-centred hedge mean.
That estimator equals the physical sample mean exactly, so its uncertainty is
the physical-payout Monte Carlo standard error. The corrected result and its
supersession rationale are in
`results/v2/validation/b10-independent-seed-r2j-7county-512.json`.
