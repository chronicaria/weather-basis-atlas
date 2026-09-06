# Portfolio decision memo

## Question

Can a July CDD portfolio retain geographic natural offsets before it purchases weather protection?

## Decision identity

`decision:ad76dfc4e86370d716256a677984d75a56a7ed451f48b79d54e44230a4b7b2fd` · scenario `sha256:ac7236e86321bb268817ecc41bf11d1eb438167651b38160ad1ddb12103f5ed3`

## Holdings and implementation


Positions: `[4.6205112453188075, 9.506492443934514, 2.1134812890405374, 1.5098517971641148]`

Status: `optimal`; objective: `es`.

## Cost and risk


Deterministic cost: `23453.073247617223`; ES: `27668.285101293277`; variance: `79235965.62195994`.

## Binding constraints

max_active, max_stations.

## Adverse scenarios

Scenario-level tail attribution is available from the retained scenario-set identity; this memo does not relabel physical paths as market prices..

## Uncertainty

Representative physical predictive scenarios and illustrative physical expected-payout pricing; no observed or executable market quote.

## Reproduction

Sources: r2j-production:5a05191c413e06cd2e0711eeb94bfbd52f3d43a81c9aad8b3f99bb03609a07d9. Run `uv run python -c "from pathlib import Path; from weather_basis.research.publishing import compile_sample_books; compile_sample_books(Path('.'), Path('var/shards/v2/scenarios.build/sha256-750b533a8f349990e6b01b1bb9853e32a163c111291a468417ea8d17f63cf609/chunks'), Path('results/v2/books/r2j-production-final/offline-10000'))"`.
