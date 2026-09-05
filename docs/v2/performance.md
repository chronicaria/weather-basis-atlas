# Compute evidence

This record distinguishes executed measurements from targets. The compact machine-readable companion is [`compute-final-evidence.json`](../../results/v2/validation/compute-final-evidence.json).

The representative 3,107-county, 2,000-path kernel shard completed in 25.04 seconds with 4.00 GiB peak RSS. Its completed artifact is recorded in [`var/runs/bench-one/report.json`](../../var/runs/bench-one/report.json).

The exact-cutoff daily-fit cache built the 2022-02-28 fit in 11.46 seconds, then loaded the same identified fit in 0.121 seconds with identical standardized-residual hash. Two independent exact-cutoff fits under two workers and one BLAS thread completed in 17.87 seconds at 4.78 GiB peak RSS. These measurements support at most two workers; they do not support a four-worker claim.

The executed national R2j stream covered 3,107 counties, 18 stations, and 10,000 paths. It published 3,112 files in 293.19 seconds with 2.79 GiB peak RSS. National scenario QC checked 437,500,000 stored values and records the float32 storage / float64 accumulation rounding bound separately from scientific equivalence.

Execution tests cover atomic publication, resume reuse, corruption quarantine and recomputation, and recursive chunk-file inventory. The latest focused run passed 10 tests. The full DAG has not yet completed: v3 was rejected by the Pages size cap, v4 was intentionally interrupted before the directory-output executor fix, and v5 remains pending. No general full-pipeline performance target is claimed.
