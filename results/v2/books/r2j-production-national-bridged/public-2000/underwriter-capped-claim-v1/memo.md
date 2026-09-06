# Portfolio decision memo

## Question

What does a capped July CDD claim add to a labelled illustrative underwriter book before and after permitted protection?

## Decision identity

`decision:590b85657419e6fc227523652b35091081220d48534adaca06a032cf3fcd3682` · scenario `sha256:38e2708d2a7e5372a39e5ce7aca29a2984ac41550d6f69a86c09e12c1a0e8503`

## Holdings and implementation


Positions: `[4.1704720555439305, 0.8447183242875209, 5.616579668654218]`

Status: `optimal`; objective: `es`.

## Cost and risk


Deterministic cost: `15569.691300304588`; ES: `18503.80917047349`; variance: `36849132.702788025`.

## Binding constraints

max_active, max_stations.

## Adverse scenarios

Scenario-level tail attribution is available from the retained scenario-set identity; this memo does not relabel physical paths as market prices..

## Uncertainty

Representative physical predictive scenarios and illustrative physical expected-payout pricing; no observed or executable market quote.

## Reproduction

Sources: r2j-production:e27775903543a346d74aff86fc6fa4e0fc967fcb78eba8f0965de1090e490479. Run `uv run python -c "from pathlib import Path; from weather_basis.research.publishing import compile_sample_books; compile_sample_books(Path('.'), Path('var/r2j-production-national-10000-bridged'), Path('results/v2/books/r2j-production-national-bridged/public-2000'))"`.
