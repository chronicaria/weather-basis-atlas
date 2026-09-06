# Portfolio decision memo

## Question

What does a capped July CDD claim add to a labelled illustrative underwriter book before and after permitted protection?

## Decision identity

`decision:7d59fd58d61ac620497b4a2ac6a66b7c192875ee364c7371cf8175180f72726d` · scenario `sha256:38e2708d2a7e5372a39e5ce7aca29a2984ac41550d6f69a86c09e12c1a0e8503`

## Holdings and implementation


Positions: `[7.030229784275416, 2.484090107375991]`

Status: `optimal`; objective: `es`.

## Cost and risk


Deterministic cost: `16143.840976439351`; ES: `18735.287517509096`; variance: `37826258.64499983`.

## Binding constraints

max_active, max_stations.

## Adverse scenarios

Scenario-level tail attribution is available from the retained scenario-set identity; this memo does not relabel physical paths as market prices..

## Uncertainty

Representative physical predictive scenarios and illustrative physical expected-payout pricing; no observed or executable market quote.

## Reproduction

Sources: r2j-production:e54dea3e624df6492837b0d40c5b484745c2ff659e2656b2a2ae31bc0f02aedd. Run `uv run python -c "from pathlib import Path; from weather_basis.research.publishing import compile_sample_books; compile_sample_books(Path('.'), Path('var/shards/v2/scenarios.build/sha256-750b533a8f349990e6b01b1bb9853e32a163c111291a468417ea8d17f63cf609/chunks'), Path('results/v2/books/r2j-production-final/public-2000'))"`.
