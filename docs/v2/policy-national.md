# National R01 reconstruction protocol

R01 is registered before reading reconstructed results: nearest eligible is the
baseline, prior-best is the challenger, and the primary result is D06
replication-MSE HE on each county/pair's exact common outer seasons. The
predeclared practical-equivalence bands are 0.00, 0.02, and 0.05 HE. Inference
clusters by chronological origin; paths and counties are not independent years.

`reconstruct_national` reads one retained rolling tensor at a time. It rebuilds
decision eligibility from the station registry's `first_test_season` and uses
only prior residual history or current prior-fit R² to choose. It uses the
current residual only as later `evaluation_scoreable`, so a held-out missing
station outcome cannot switch the historical choice.

The retained V1 tensors are adequate only together with retained county anomaly
tables, station support metadata, and the nearest-station mapping. They do not
carry a decision eligibility mask, so the reconstruction publishes this support
assumption in `tensor_adequacy.parquet`. A missing required component fails the
pair rather than relabelling its V1 outcome-filtered result.

Current pricing requires an explicit 2026-07-01 (or supplied) valuation and
concrete contract window. Physical and unhedged indications remain available
when a station hedge is unavailable. Hedged indications require aligned finite
station paths for the frozen selected station; V2 never uses a county-self or
atlas-ratio substitute.
