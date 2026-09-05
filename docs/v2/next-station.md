# B26 next-station pilot

[`config/research/next-station-v2.yaml`](../../config/research/next-station-v2.yaml) is the frozen protocol for the bounded Nebraska pilot. It starts from `regional-heating-v1`: January HDD shortfall exposures for Douglas (`31055`, 115 USD/DD), Lancaster (`31109`, 140 USD/DD), and Hall (`31079`, 75 USD/DD). Each county and station strike is the median of exactly the 30 seasons before the origin.

The baseline is the 13 registry `cme` station IDs. The only additions are the five already-present, registry `nebraska` series: Grand Island `USW00014935`, Lincoln `USW00014939`, Omaha `USW00014942`, North Platte `USW00024023`, and Scottsbluff `USW00024028`. They are observed-data research proxies. Their metadata, coordinates, coverage and January QC are checked at every origin; none is represented as an exchange listing or executable hedge.

Origins are 2010--2025. At each origin the pilot requires 20 common prior observations across the three county indexes and all 18 registered station series, complete/unfilled January QC for every station, and a 30-season preceding training window. It compares the baseline, each one-station addition, one predeclared Omaha+Scottsbluff combination, and a training-selected one-addition candidate. The selected candidate is frozen from training objective values before the realized origin is read. If a selected station's later outcome is missing, that frozen decision is unscoreable; the code does not choose a replacement.

For each variance and ES90 objective, the long-only station-HDD puts pay 20 USD/DD below their prior training median. The unit premium is its prior physical mean payout plus 20 USD per contract. Positions are whole contracts, capped at 100 per station, with a 50,000 USD cash budget. ES uses the finite integer program; variance floors the feasible continuous solution to whole contracts and reevaluates the actual ledger. The report also reruns the same design with the fee set to zero. These are illustrative physical premiums, not market quotes.

The held-out ledger is `loss - long payoff + deterministic cost`, with cost included once. It uses observed historical origin rows, not independent simulated paths. Uncertainty is a 2,000-resample origin-clustered descriptive bootstrap; 2023--2025 are explicitly consumed development years. The eventual report exposes map-ready candidate coordinates, admission disposition, origin-level selected actions, costs, and a `promote`, `retain_research`, `inconclusive`, or `stop_missing_evidence` conclusion.

The writer pairs each strategy only to the baseline on the same scored origins, then resamples those origins as clusters. It reports variance or ES90 gain as baseline risk minus strategy risk, paired coverage, missing later outcomes, base-versus-zero-fee cost sensitivity, and selected-addition disagreement between variance and ES90. It never treats station columns or duplicated sensitivity rows as independent observations. The predeclared adjudication promotes only when the training-selected addition has at least ten paired origins and a positive lower 95% gain bound for both objectives; a positive but unsupported point result remains `retain_research`, any other scoreable result is `inconclusive`, and insufficient paired support is `stop_missing_evidence`.

After core acceptance, the pilot is prepared through the normal stage planner, then run from its frozen plan:

```bash
uv run wba v2 plan --stage research.next_station --spec config/research/v2.yaml \
  --vintage config/vintages/v1-frozen.yaml --profile representative \
  --out var/runs/b26-next-station-plan.json
uv run wba v2 run --plan var/runs/b26-next-station-plan.json --resume
```
