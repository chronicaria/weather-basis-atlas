# V2 public cases and supplied books

The three supplied books are source-controlled JSON requests, rather than
hand-written site examples: `regional-heating-v1`, `multi-location-cooling-v1`,
and `underwriter-capped-claim-v1`. Their holdings use the public CSV fields
`row_id`, `kind`, `entity_id`, `amount`, `units`, and `currency`, plus a weather
coordinate (`fips`, `pair`, `index_definition_id`, and `window_id`). `entity_id`
is exactly `FIPS:PAIR`. All amounts are labelled illustrative USD per degree day.
Each row declares `loss_kind`, `base`, and `budget`. The budget is the weather
index threshold used by the loss function; it is never a cash budget. It equals
the row's frozen trailing-30-year county-index burn median through 2026 and has
the semantic ID `burn-median-30y-through-2026-v1`. Amount and fee assumptions
also carry their own IDs.

The regional heating book holds Omaha/Douglas, Lincoln/Lancaster, and Grand
Island/Hall January HDD exposure. The cooling book holds Omaha, Lincoln, North
Platte/Lincoln County, and Scottsbluff/Scotts Bluff County July CDD exposure.
The underwriter book adds a capped Lincoln July CDD claim to two existing
illustrative cooling exposures. Neither implies an observed premium, executable
station quote, or real policyholder loss.

The public projections report `partial` until B11 publishes a common predictive
scenario matrix. That status means the canonical holdings can be inspected,
exported, and restored, while portfolio ES, natural offsets, optimization and
incremental capital remain unavailable. The historical R03 comparison is
exploratory observed-index evidence, not a replacement for that predictive
ledger.

Nebraska keeps all five required mappings: Omaha/Douglas `31055` with Eppley
`USW00014942`, Lincoln/Lancaster `31109` with Lincoln AP `USW00014939`, Grand
Island/Hall `31079` with Grand Island `USW00014935`, North Platte/Lincoln County
`31111` with North Platte `USW00024023`, and Scottsbluff/Scotts Bluff `31157`
with Scottsbluff `USW00024028`. Case rows cover HDD-01 and CDD-07 and retain
inconclusive outcomes.

`compile_sample_books(root, scenario_dir, out)` consumes a supplied B11 common
monthly matrix and writes available finite-ledger results for all three books.
It uses no locally generated weather paths. Its output retains the B11 artifact's
representative-only production status, which is a release gate rather than a
reason to relabel a valid supplied-matrix calculation as partial.

`weather_basis.research.publishing.decision_record` projects an accepted
`OptimizationResult` to a machine-readable request/result record. `export_decision`
writes holdings and result CSVs plus request/result JSON. `restore_decision`
verifies the content-derived decision ID; a restored record must have canonical
JSON equality with its source. `decision_memo` renders Markdown or HTML from the
same record and includes holdings, implemented positions, cost/risk, bindings,
adverse scenarios, uncertainty, IDs, and an exact maintenance command.
