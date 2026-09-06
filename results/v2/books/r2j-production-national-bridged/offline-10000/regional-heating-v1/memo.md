# Portfolio decision memo

## Question

How much January HDD shortfall risk remains across a declared Nebraska operating region?

## Decision identity

`decision:7c3ed314ad45be502914db662bbff97005dbebab9fe7aa6f33f401014089a4c6` · scenario `sha256:ac7236e86321bb268817ecc41bf11d1eb438167651b38160ad1ddb12103f5ed3`

## Holdings and implementation


Positions: `[8.522337219296894, 8.276770237881294, -0.0]`

Status: `optimal`; objective: `es`.

## Cost and risk


Deterministic cost: `29582.58498597853`; ES: `55420.26237912661`; variance: `244970737.9741983`.

## Binding constraints

lower_bounds.

## Adverse scenarios

Scenario-level tail attribution is available from the retained scenario-set identity; this memo does not relabel physical paths as market prices..

## Uncertainty

Representative physical predictive scenarios and illustrative physical expected-payout pricing; no observed or executable market quote.

## Reproduction

Sources: r2j-production:97f48305b46b74f0afe994b3f2d3c033fa6930e69874ab011d61129ecf89fba4. Run `uv run python -c "from pathlib import Path; from weather_basis.research.publishing import compile_sample_books; compile_sample_books(Path('.'), Path('var/r2j-production-national-10000-bridged'), Path('results/v2/books/r2j-production-national-bridged/offline-10000'))"`.
