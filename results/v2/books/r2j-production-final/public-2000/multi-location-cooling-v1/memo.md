# Portfolio decision memo

## Question

Can a July CDD portfolio retain geographic natural offsets before it purchases weather protection?

## Decision identity

`decision:4dcad07831bd9448d5e85905c523aafe738619a676b1bb2f036eca007ce1009e` · scenario `sha256:38e2708d2a7e5372a39e5ce7aca29a2984ac41550d6f69a86c09e12c1a0e8503`

## Holdings and implementation


Positions: `[5.963548013723859, 7.457341415122844, 1.5132944853465147, 2.22565484411011]`

Status: `optimal`; objective: `es`.

## Cost and risk


Deterministic cost: `24036.99150710286`; ES: `28240.112751684013`; variance: `73493445.64751732`.

## Binding constraints

max_active, max_stations.

## Adverse scenarios

Scenario-level tail attribution is available from the retained scenario-set identity; this memo does not relabel physical paths as market prices..

## Uncertainty

Representative physical predictive scenarios and illustrative physical expected-payout pricing; no observed or executable market quote.

## Reproduction

Sources: r2j-production:e54dea3e624df6492837b0d40c5b484745c2ff659e2656b2a2ae31bc0f02aedd. Run `uv run python -c "from pathlib import Path; from weather_basis.research.publishing import compile_sample_books; compile_sample_books(Path('.'), Path('var/shards/v2/scenarios.build/sha256-750b533a8f349990e6b01b1bb9853e32a163c111291a468417ea8d17f63cf609/chunks'), Path('results/v2/books/r2j-production-final/public-2000'))"`.
