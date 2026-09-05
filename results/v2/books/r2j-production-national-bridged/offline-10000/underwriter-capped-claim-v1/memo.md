# Portfolio decision memo

## Question

What does a capped July CDD claim add to a labelled illustrative underwriter book before and after permitted protection?

## Decision identity

`decision:9d3bc5c96ae6cdd5ad5cc7f2a7f2e8c2e2194bec64da028ea147f91a14a72e42` · scenario `sha256:ac7236e86321bb268817ecc41bf11d1eb438167651b38160ad1ddb12103f5ed3`

## Holdings and implementation


Positions: `[3.4889215621578935, -0.0, 7.342840071675672]`

Status: `optimal`; objective: `es`.

## Cost and risk


Deterministic cost: `15064.01171068165`; ES: `18179.193109332107`; variance: `39036836.61677846`.

## Binding constraints

lower_bounds.

## Adverse scenarios

Scenario-level tail attribution is available from the retained scenario-set identity; this memo does not relabel physical paths as market prices..

## Uncertainty

Representative physical predictive scenarios and illustrative physical expected-payout pricing; no observed or executable market quote.

## Reproduction

Sources: r2j-production:97f48305b46b74f0afe994b3f2d3c033fa6930e69874ab011d61129ecf89fba4. Run `uv run python -c "from pathlib import Path; from weather_basis.research.publishing import compile_sample_books; compile_sample_books(Path('.'), Path('var/r2j-production-national-10000-bridged'), Path('results/v2/books/r2j-production-national-bridged/offline-10000'))"`.
