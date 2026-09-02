# Decision 0006: run rolling daily model fits serially

Date: 2026-09-02

Decision: set `simulate.workers` to 1 for production rolling-origin daily R2
fits. The simulator remains county-chunked and deterministic; model formulas,
origins, draw counts, seed children, and output schemas are unchanged.

Supersedes: Section 7.4's operational eight-worker default and the `workers: 8`
entry in Section 16. It does not supersede D-60 through D-66.

Reasoning: macOS uses spawned workers, so the fitted daily panel and sufficient
statistics are not safely shared copy-on-write. Eight concurrent full fits
would exceed the registered 12 GB process budget. Serial execution preserves
the registered statistical protocol and is slower but safe.

Evidence: a pre-production benchmark of one complete registered pair-origin
(3,107 counties by 2,000 draws) took 18.6 seconds and measured 6.93 GB maximum
RSS / 11.22 GB peak process footprint. The simulation draw chunk itself is
bounded; the dominant cost is the fitted daily panel and mean sufficient
statistics. The production run writes the same measurement fields to
`results/tournament/benchmark.json`.

Consequences: the full tournament is expected to take roughly three hours and
runs without concurrent model jobs. The 12 GB gate and all numerical gates are
unchanged.
