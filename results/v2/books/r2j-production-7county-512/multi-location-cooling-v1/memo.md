# Portfolio decision memo

## Question

Can a July CDD portfolio retain geographic natural offsets before it purchases weather protection?

## Decision identity

`decision:16d35fce101f7045807927d7bb3a18da5d5a5e7fb99547ebb039ef4161b74143` · scenario `sha256:da29be1b324f78afb0a81aaa699abbb49ee59ba1be23800ba806d49e23c82bd7`

## Holdings and implementation


Positions: `[237.4161511419106, 0.0, 41.94411813110919, 0.0]`

Status: `optimal`; objective: `es`.

## Cost and risk


Deterministic cost: `32991.196915248875`; ES: `36970.98331323807`; variance: `80403997.52388296`.

## Binding constraints

lower_bounds.

## Adverse scenarios

Scenario-level tail attribution is available from the retained scenario-set identity; this memo does not relabel physical paths as market prices..

## Uncertainty

Representative physical predictive scenarios and illustrative physical expected-payout pricing; no observed or executable market quote.

## Reproduction

Sources: r2j-production:c3651c85eb14665094456e3637e17987a294279b3f50454b32304d5aec05dfa2. Run `uv run python -c "from pathlib import Path; from weather_basis.research.publishing import compile_sample_books; compile_sample_books(Path('.'), Path('var/r2j-production-7county-512'), Path('results/v2/books/r2j-production-7county-512'))"`.
