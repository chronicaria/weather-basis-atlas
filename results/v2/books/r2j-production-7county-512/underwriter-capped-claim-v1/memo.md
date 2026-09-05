# Portfolio decision memo

## Question

What does a capped July CDD claim add to a labelled illustrative underwriter book before and after permitted protection?

## Decision identity

`decision:d0a4456f9e183dbd60aa6ed5b0a49f1eed4e8354b30010f90b410e7ee3d82240` · scenario `sha256:da29be1b324f78afb0a81aaa699abbb49ee59ba1be23800ba806d49e23c82bd7`

## Holdings and implementation


Positions: `[172.48520185886233, 0.0, 0.0]`

Status: `optimal`; objective: `es`.

## Cost and risk


Deterministic cost: `21806.31534211531`; ES: `25346.14172660899`; variance: `40176588.13729641`.

## Binding constraints

lower_bounds.

## Adverse scenarios

Scenario-level tail attribution is available from the retained scenario-set identity; this memo does not relabel physical paths as market prices..

## Uncertainty

Representative physical predictive scenarios and illustrative physical expected-payout pricing; no observed or executable market quote.

## Reproduction

Sources: r2j-production:c3651c85eb14665094456e3637e17987a294279b3f50454b32304d5aec05dfa2. Run `uv run python -c "from pathlib import Path; from weather_basis.research.publishing import compile_sample_books; compile_sample_books(Path('.'), Path('var/r2j-production-7county-512'), Path('results/v2/books/r2j-production-7county-512'))"`.
