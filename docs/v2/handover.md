# V2 handover

[Weather Basis Atlas V2 is live](https://chronicaria.github.io/weather-basis-atlas/).
B00–B27 and G0–G8 are complete within the declared national research scope.
[Release v2.0.0-20260905](https://github.com/chronicaria/weather-basis-atlas/releases/tag/v2.0.0-20260905)
pins source `59e8c3702ea56770249301187d004811b8132186`, release
`release:306bdf8f6a3a1c31762f00b668d43e26f1cf0a33273dc51baf23f9d7635bef74`,
and bundle `bundle:500a17e4202c6bc05fad8e2f7daa993cdedc204dc594397a3006c42210d85ae6`.
The [completion record](../../results/v2/validation/completion.json) binds the
executed gates to retained proof hashes. Pages run 34001239283 succeeded;
all live routes and all three public portfolio optimizations passed.

## What the workbench supports

Explore and Compare retain all 3,107 counties and 14 index/month pairs. Contract
Lab evaluates linear, call, put, capped, spread and collar cashflows, including
an option on a seasonal strip and the distinct sum of monthly options. Portfolio
Lab supplies heating, cooling and underwriting books, an empty book, local CSV
import, real editable optimization, Scenario Room, and restorable decision
JSON, memo and CSV exports. The public solver supports up to six counties,
24 exposure rows, 39 hedge columns and 12 months on the exact 2,000-path prefix
of the identified 10,000-path offline simulation.

The cashflow convention is residual loss = gross loss − hedge cashflow + cost.
ES90 uses fractional probability mass. Variance, MSE, ES and minimum-cost ES
have actual Python and browser implementations with bounds, budgets, exposure
constraints and lot treatment. Browser-imported holdings stay local.

## Findings and limits

- The matched national table has 43,148 evaluable and 350 unavailable county/pair
  rows. Prior-best selection beats nearest in 6,355 evaluable rows, ties in
  3,859 and loses in 32,934 (76%), with a median difference near −4 percentage
  points of hedge effectiveness; the nearest station is the better default in
  most records, and the registered equivalence bands were not tallied here. Historical scoreability and current
  as-of eligibility are separate. All 43,498 quote records were checked against
  the actual selected station; 417 station hedges are explicitly unavailable.
- Three illustrative books have lower optimized ES90 than their unhedged
  baselines on the accepted scenarios. The public/offline comparison and
  fixed-position revaluation are retained in
  [the book report](../../results/v2/books/r2j-production-final/public-vs-offline-comparison.json).
  Four-objective Python/browser parity is separately recorded in
  [the solver report](../../results/v2/validation/final-four-objective-parity.json).
- R01–R05 and the Nebraska case retain negative and inconclusive results.
  R04 has only two scoreable origins and is inconclusive; its descriptive
  advantage does not prove model superiority. The 2023–2025 outcomes are
  consumed development evidence, never an untouched confirmation set.
- The next-station pilot met its registered research-promotion rule over all
  16 origins. A training-selected addition reduced ES90 by $10,602.29, with
  origin-clustered 95% interval $4,507.06–$16,932.61. Variance and ES selected
  the same added station in 13 origins. These are station research proxies,
  not new exchange listings or evidence of executable liquidity. See
  [the complete pilot and supersession record](../../results/v2/next-station/acceptance-a6e569904e030545.json).
- The national stream generated 10,000 paths for 3,107 counties and 18 stations
  in 293.19 seconds at 3.00 GB peak RSS. Exact-cutoff reuse and two-worker
  measurements are real; a general fourfold full-pipeline speedup was not
  established. [Performance evidence](performance.md) preserves the measured
  targets and unsuccessful predecessor builds.
- Physical expected payouts, explicit assumed risk-transfer charges, and
  unavailable market observations remain distinct. Data are a frozen
  retrospective vintage, with May 31 observation cutoff and July 1 valuation
  convention. Model indications and illustrative economic exposures are not
  executable market quotes or observed customer-loss models.

## Maintenance and recovery

Start with [the quickstart](quickstart.md), [CLI reference](commands.md),
[architecture](architecture.md), [interfaces](interfaces.md),
[artifact lifecycle](artifacts.md), and [release runbook](release.md).
The checked-in `config/releases/v2-candidate.lock.json` pins the final public
source, scientific manifests, configuration, presentation and V1 archive.

The GitHub Release tag is `v2.0.0-20260905`. Its asset inventories preserve raw
inputs, prepared panels, fit cache, national scenarios, core stages, the final
changed stages, complete public source, a compact release leaf, V1 archive,
and a prior sealed candidate. Recover the final scientific source in the exact
order documented by
[the final research asset ledger](../../results/v2/validation/final-research-assets.json).
The source helper refuses an existing output directory. A presentation rebuild
never reruns a weather model.

A release is accepted only after `wba v2 release verify` passes. To recover a
previous sealed directory into a fresh target, run:

```bash
uv run wba v2 release rollback --bundle build/releases/v2-prior \
  --target build/recovery/v2-prior
```

[The prior recovery proof](../../results/v2/validation/prior-bundle-recovery.json)
records actual extraction, byte verification, recovery and deliberate-copy
tamper rejection. The retained prior V2 candidate is not described as a previous
public V2 release. The public V1 archive remains available under `/v1/`, and
its tracked source/history were retained explicitly; no history rewrite was
performed. Pages deploys only the downloaded, checksum-verified, sealed asset.

## Unadmitted conditional tracks

These are explicit extension dispositions, not missing core features:

| Track | Required admission evidence |
| --- | --- |
| Decision-time forecasts | Archived issue-time/lead-time fields, correction history and paired rolling-origin value tests against the frozen no-forecast baseline. |
| Market calibration or execution | Licensed timestamped bid/ask/trade observations, exact product/calendar mapping, admissible use rights and out-of-sample pricing/cost evidence. |
| Real energy or customer exposures | Authorized measured consumption/revenue/load data, an identified economic loss model and validation of exposure scaling; private storage/authentication only if actual private data enters scope. |
| Rain, snow, wind, solar and international products | Admitted variable/QC/settlement sources, regional/calendar/currency contracts, persistence and tail validation, and cross-variable dependence evidence before joint diversification claims. |
| Dynamic or robust protection | Registered competing model probabilities or decision-time forecasts/quotes, transaction costs and margin paths, and an evaluated promotion rule. |

Use the proof register and execution ledger to resume maintenance. The historical
specification and audits are preserved; current results do not rewrite their
original claims.

## V2.1 presentation release

V2.1 (September 2026) redesigned `apps/site/` for a public reader without
touching any scientific artifact: plain-language copy, formatted numbers with
units, named map layers with legends, metric tiles with one-line meanings,
simulated-season charts, a stepped Portfolio Lab, a documentation shell for
Research, and provenance identifiers moved into collapsed blocks. The
presentation-only release path (`scripts/presentation_lock.py`,
`scripts/serve_site.py`) is documented in [the release runbook](release.md).
