# V2 registered research experiments

The frozen protocol is [`config/research/experiments-v2.yaml`](../../config/research/experiments-v2.yaml). Its content hash is copied into every report before results are read. R02, R03 and R05 use annual HDD-01 and CDD-07 indexes from the frozen local county and station panels. Every station choice and coefficient fit uses years before the scored origin. Differences use paired origins; the reported interval resamples origins, not simulated paths.

`run_research(root, out=None, experiments=("R02", "R03", "R05"))` publishes each experiment beneath `results/v2/experiments/<experiment>/<protocol-derived-id>/`. Each directory has `report.json`, row-level `rows.parquet`, and an atomic content-addressed manifest.

R02 is a five-county Nebraska representative sparse-basket study. The local station is the declared nearest baseline, and a maximum-three-station OLS basket is selected only within each preceding window. Costs are explicitly registered as illustrative index-unit costs; the present physical-index residual comparison does not claim executable prices.

R03 compares separately fitted one-station county hedges with a jointly fitted, maximum-five-station book on the same observed county-year coordinates. The result is labelled historical observed-index evidence. It does not substitute for B11's predictive common-scenario evaluation, which remains required before interpreting simulated joint-tail behavior.

R05 is a bounded national sensitivity screen across two chronological windows and the 13 CME-reference versus 18 extended station universes. Its difficult/ambiguous labels describe those four settings only. It is not final national validation and awaits the corrected policy and common-scenario inputs.

Nebraska maps the five required city labels to county and source station identifiers: Omaha/Douglas `31055`/`USW00014942`, Lincoln/Lancaster `31109`/`USW00014939`, Grand Island/Hall `31079`/`USW00014935`, North Platte/Lincoln `31111`/`USW00024023`, and Scottsbluff/Scotts Bluff `31157`/`USW00024028`. Both HDD and CDD are included; poor and ambiguous outcomes remain in the row-level reports.

## B26 next-station pilot

The completed pilot report is
[`next_station_report.json`](../../results/v2/next-station/sha256-a6e569904e030545f18e1e490d64febd2657d45ed0e99af8e9192c7c8d1b9ddf/next_station_report.json),
with its paired rows beside it. It evaluates registered additions to the
five-county Nebraska proxy book using chronological, prior-only choices. The
report disposition is `promote` for the research feature: the training-selected
one-addition ES comparison has 16 paired origins, a gain of 10,602.29, and a
95% origin-bootstrap interval of 4,507.06 to 16,932.61. This is a research
promotion, not evidence that a listed contract can be traded.

The 2023–2025 period is consumed exploratory/development evidence. County and
GHCN indexes remain retrospective public research proxies, and the admission
table explicitly makes no exchange-availability claim. The report's cost
table contains registered illustrative deterministic costs; it is not a record
of exchange transactions, bids, asks, or settlements.
