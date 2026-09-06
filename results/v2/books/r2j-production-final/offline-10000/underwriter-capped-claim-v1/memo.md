# Portfolio decision memo

## Question

What does a capped July CDD claim add to a labelled illustrative underwriter book before and after permitted protection?

## Decision identity

`decision:29ade152d29000eb212a70f8b7743998962e1c06bfd54bd75ee9c1ce7b9ab05a` · scenario `sha256:ac7236e86321bb268817ecc41bf11d1eb438167651b38160ad1ddb12103f5ed3`

## Holdings and implementation


Positions: `[6.946623858844223, 2.570812150294591]`

Status: `optimal`; objective: `es`.

## Cost and risk


Deterministic cost: `15867.181794696504`; ES: `18642.228705987436`; variance: `40238866.672499366`.

## Binding constraints

max_active, max_stations.

## Adverse scenarios

Scenario-level tail attribution is available from the retained scenario-set identity; this memo does not relabel physical paths as market prices..

## Uncertainty

Representative physical predictive scenarios and illustrative physical expected-payout pricing; no observed or executable market quote.

## Reproduction

Sources: r2j-production:5a05191c413e06cd2e0711eeb94bfbd52f3d43a81c9aad8b3f99bb03609a07d9. Run `uv run python -c "from pathlib import Path; from weather_basis.research.publishing import compile_sample_books; compile_sample_books(Path('.'), Path('var/shards/v2/scenarios.build/sha256-750b533a8f349990e6b01b1bb9853e32a163c111291a468417ea8d17f63cf609/chunks'), Path('results/v2/books/r2j-production-final/offline-10000'))"`.
