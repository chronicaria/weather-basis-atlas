# Portfolio decision memo

## Question

How much January HDD shortfall risk remains across a declared Nebraska operating region?

## Decision identity

`decision:24cb8240fd0f5b237f004dd446d1aab1381ef2f07910ba6b66a65b77d0ec37e9` · scenario `sha256:ac7236e86321bb268817ecc41bf11d1eb438167651b38160ad1ddb12103f5ed3`

## Holdings and implementation


Positions: `[8.522337219296894, 8.276770237881294, -0.0]`

Status: `optimal`; objective: `es`.

## Cost and risk


Deterministic cost: `29582.58498597853`; ES: `55420.262379126616`; variance: `244970737.9741983`.

## Binding constraints

lower_bounds.

## Adverse scenarios

Scenario-level tail attribution is available from the retained scenario-set identity; this memo does not relabel physical paths as market prices..

## Uncertainty

Representative physical predictive scenarios and illustrative physical expected-payout pricing; no observed or executable market quote.

## Reproduction

Sources: r2j-production:5a05191c413e06cd2e0711eeb94bfbd52f3d43a81c9aad8b3f99bb03609a07d9. Run `uv run python -c "from pathlib import Path; from weather_basis.research.publishing import compile_sample_books; compile_sample_books(Path('.'), Path('var/shards/v2/scenarios.build/sha256-750b533a8f349990e6b01b1bb9853e32a163c111291a468417ea8d17f63cf609/chunks'), Path('results/v2/books/r2j-production-final/offline-10000'))"`.
