# V2 command reference

This reference is maintained from `application/v2_cli.py` and the canonical
stage registry in `application/stages.py`. V1 commands remain available under
`wba`; V2 work uses only the `wba v2` namespace.

| Command | Required arguments | Effect |
| --- | --- | --- |
| `wba v2 plan` | `--stage`, `--out` | Validates configuration, resolves the stage DAG and input IDs, and writes a frozen no-execution plan. |
| `wba v2 run` | `--plan` | Runs exactly the frozen plan. It rejects changed science, inputs, coordinates, or producers. |
| `wba v2 verify` | `--gate`, `--plan`, `--candidate`, or `--seed-validation PRIMARY SECONDARY` | Runs named gates and validates supplied plan/candidate/seed evidence without refitting. |
| `wba v2 bench` | `--stage`, `--out` | Plans and executes a declared representative profile through registered stages. |
| `wba v2 release build` | `--lock`, `--out` | Builds a sealed bundle from an explicit lock. |
| `wba v2 release verify` / `inspect` | `--bundle` | Verifies or reads a sealed bundle. |
| `wba v2 release rollback` | `--bundle`, `--target` | Verifies then restores to the explicit local target. |
| `wba v2 serve` | `--bundle` | Serves one verified bundle on loopback; default port is 8765. |

`verify --candidate PATH` passes an existing candidate-evidence JSON to the
acceptance validator. It does not generate artifacts, accept a release, or
invent a passing gate state. `plan` and `bench` accept `--spec`, `--vintage`, `--profile`, `--request`,
`--workers`, and `--memory-gib`. They accept `--pair`, `--origin`, and
`--county-panel` only when the selected stage declares that selector. The
county panel is a JSON FIPS array or `{"fips": [...]}`. Repeated selector
values, selectors that a stage does not consume, out-of-spec pairs, and
conflicting request-file selectors fail before a plan is emitted. `run` accepts
only execution overrides (`--workers`, `--memory-gib`, `--resume`, `--force`).
Workers must be one or two; memory is greater than zero, at most 12 GiB, and at
least 4 GiB per worker.

`verify --seed-validation PRIMARY SECONDARY` requires two explicit frozen
`r2j-production-stream` manifests. The validator checks compatible declared
scenario/global-plan/fit/source support, distinct seed identities, and the
bounded labelled county/station and ticket panel before it compares persisted
per-ticket metrics. It performs no scenario generation and no tournament. The
current primary benchmark is `var/r2j-production-7county-512/manifest.json`;
the command remains unavailable until a separately labelled secondary manifest
is supplied.

| Stage | Direct dependencies | Accepted selectors |
| --- | --- | --- |
| `inputs.audit` | — | — |
| `panels.prepare` | `inputs.audit` | pair |
| `atlas.evaluate` | `panels.prepare` | pair |
| `atlas.select_asof` | `atlas.evaluate` | pair |
| `models.fit` | `panels.prepare` | — |
| `tournament.execute` | `models.fit` | origin |
| `models.select` | `tournament.execute` | — |
| `scenarios.build` | `models.select` | county panel |
| `payoffs.build` | `scenarios.build` | — |
| `quotes.build` | `payoffs.build`, `atlas.select_asof`, `scenarios.build` | pair, county panel |
| `portfolios.evaluate` | `payoffs.build`, `scenarios.build` | — |
| `portfolios.optimize` | `portfolios.evaluate`, `payoffs.build`, `scenarios.build` | — |
| `cases.build` | `quotes.build`, `portfolios.optimize`, `scenarios.build`, `atlas.evaluate`, `atlas.select_asof` | — |
| `site.build` | `cases.build` | — |
| `research.next_station` | `cases.build` | — |
| `release.verify` | `site.build` | — |

The fixture command used by the Makefile is bounded and exercises the actual
portfolio path:

```bash
make v2-fixture-plan
make v2-fixture-run
```

For a direct equivalent:

```bash
uv run wba v2 plan --stage portfolios.optimize --spec config/research/v2.yaml \
  --vintage config/vintages/v1-frozen.yaml --profile fixture \
  --request tests/fixtures/v2/portfolio_request.json --out var/runs/v2-fixture-plan.json
uv run wba v2 run --plan var/runs/v2-fixture-plan.json --resume
```

Exit status `2` is an invalid request, `3` a missing dependency, `4` a failed
verification gate, and `5` a runtime failure. Planning never fetches sources;
missing inputs are recorded in the plan and cause `run` to fail.
