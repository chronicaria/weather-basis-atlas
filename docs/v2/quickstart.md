# V2 quickstart

Use a frozen plan before executing work. Planning validates inputs and records
the exact stage graph without fetching data.

```bash
uv run wba v2 plan --stage portfolios.optimize --spec config/research/v2.yaml \
  --vintage config/vintages/v1-frozen.yaml --profile fixture \
  --request tests/fixtures/v2/portfolio_request.json --out var/runs/v2-fixture-plan.json
uv run wba v2 run --plan var/runs/v2-fixture-plan.json --resume
```

For the bounded browser-path check, run `make v2-fixture-plan` then
`make v2-fixture-run`. Inspect a result through its artifact manifest and do
not treat a local shard as a release. The current final downstream evidence is
[`var/runs/v2-final-research-run.json`](../../var/runs/v2-final-research-run.json);
the sealed site leaf is `build/releases/v2-final`, verified by [the release report](../../results/v2/validation/final-release.json).

When an explicit verified bundle exists, serve only that bundle on loopback:

```bash
uv run wba v2 release verify --bundle build/releases/v2-final
uv run wba v2 serve --bundle build/releases/v2-final
```

The public workflow starts with Explore, preserves a committed county/index
selection through Compare and the labs, and exposes provenance in Research.
Local portfolio CSV imports stay in the browser. Use exported decision manifests
to restore a private or larger book; do not put holdings in a URL.
