# Compute evidence

This record distinguishes executed measurements from targets. The compact machine-readable companion is [`compute-final-evidence.json`](../../results/v2/validation/compute-final-evidence.json).

The representative 3,107-county, 2,000-path kernel shard completed in 25.04 seconds with 4.00 GiB peak RSS. Its completed artifact is recorded in [`var/runs/bench-one/report.json`](../../var/runs/bench-one/report.json).

The exact-cutoff daily-fit cache built the 2022-02-28 fit in 11.46 seconds, then loaded the same identified fit in 0.121 seconds with identical standardized-residual hash. Two independent exact-cutoff fits under two workers and one BLAS thread completed in 17.87 seconds at 4.78 GiB peak RSS. These measurements support at most two workers; they do not support a four-worker claim.

The executed national R2j stream covered 3,107 counties, 18 stations, and 10,000 paths. It published 3,112 files in 293.19 seconds with 2.79 GiB peak RSS. National scenario QC checked 437,500,000 stored values and records the float32 storage / float64 accumulation rounding bound separately from scientific equivalence.

Execution tests cover atomic publication, resume reuse, corruption quarantine and recomputation, and recursive chunk-file inventory. The full 15-stage v5 DAG completed after the directory-output executor repair: 12 stages reused accepted artifacts and three recomputed. The later final downstream research run is recorded at [`var/runs/v2-final-research-run.json`](../../var/runs/v2-final-research-run.json): eight stages reused and six recomputed after the QP fix (`payoffs.build`, `quotes.build`, `portfolios.evaluate`, `portfolios.optimize`, `cases.build`, and `research.next_station`). Its separately verified final release leaf completed in 325.15 seconds with 484,933,632-byte process peak RSS and 749,137,207 served bytes; see [the final seal](../../results/v2/validation/final-release.json). These are reuse records, not a general full-pipeline throughput target.
