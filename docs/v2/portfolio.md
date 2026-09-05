# V2 portfolio numerical contract

Portfolio arithmetic uses aligned scenario IDs. An exposure loss is positive when
it harms the portfolio and a long-unit hedge cash flow is positive when it pays
the portfolio. For signed positions `h` and terminalized deterministic cost
`C(h)`, residual loss is `R = L - G h + C(h)`. Costs enter exactly once.

`tests/fixtures/v2/portfolio_hand_cases.json` defines independent hand cases:

- a perfect long hedge and an explicit short-position vector;
- weighted fractional-tail ES, including the ES90 value 55 rather than the
  single worst observation;
- linear/call/put/capped-call/spread identities;
- a continuous solution versus actual two-unit lots, with the implemented
  residual and MSE recomputed; and
- an infeasible required-hedge/cash-budget problem.

All predictive statistics require finite, nonnegative probability weights that
sum to one. A stress scenario set with null weights is only valid for labelled
pathwise stress reporting; it is rejected for expected loss, variance, MSE and
ES optimization.

## Adapter boundary

The scenario/schema layer supplies a `ScenarioSet` with ordered scenario IDs
and optional weights, plus aligned `ScenarioMatrix` objects carrying the same
parent scenario-set ID and scenario index. The portfolio layer compiles those
objects into this finite numerical problem:

```text
losses[S], payoffs[S, J], scenario_ids[S], weights[S], candidate_ids[J],
cost model, and constraints
```

The portfolio compiler rejects mismatched IDs even when dimensions match. Its
result records the actual lot positions, objective and risk evaluated from
those positions, deterministic cost, feasibility residuals, binding
constraints, candidate-screen explanation and input hash.

## Offline and browser implementation

Offline LP/MILP uses the locked SciPy/HiGHS environment. The browser worker is
also a pinned runtime: [`apps/site/vendor/highs/MANIFEST.json`](../../apps/site/vendor/highs/MANIFEST.json)
declares highs-js 1.15.2, including `highs-1.15.2.wasm` SHA-256
`7e6432b2b26f4fab9f6d9bac55da43307c7a4b1b071cb204cb4d23e1901bc4d0`
and JS SHA-256
`6d5be3ed3cbd1ce1924cc66cc9302b50753dabdb8c6e0e815845dce7f1890033`.
The worker imports those vendored paths and caps a public calculation at six
locations, 24 exposure rows, 39 candidates, and 2,000 paths.

The browser's finite-matrix kernel shares golden hand vectors with
`tests/fixtures/v2/portfolio_hand_cases.json`. The sealed real-ui preflight
recorded browser-worker ES optimization for all three supplied books. The
public/offline comparison records each public book's browser-parity expected
shortfall and deterministic cost in
[`public-vs-offline-comparison.json`](../../results/v2/books/r2j-production-final/public-vs-offline-comparison.json).
It records values for the 2,000-path prefix; it does not establish equality
with the 10,000-path offline optimization.

The supplied books are `regional-heating-v1`, `multi-location-cooling-v1`, and
`underwriter-capped-claim-v1`. Their published constraints and frozen candidate
contracts are consumed as supplied. A user may instead provide the complete
local CSV schema (including budgets, hedge fields, and unit costs); the browser
rejects incomplete or unsupported CSV rows and does not infer missing values.
