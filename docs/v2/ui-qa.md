# V2 UI acceptance evidence

## Sealed artificial fixture

The following browser checks used the immutable fixture bundle
`build/releases/v2-ui-fixture-8` at release
`release:56c226356c33bdb5117d3deae8e0bb287cb2e6916b4ac8bfa41305f9b813d5e3`.
Its scope banner identifies it as an artificial numerical fixture, not
empirical weather evidence. It was served locally at `http://127.0.0.1:8772`.

| Journey | Evidence | Outcome |
| --- | --- | --- |
| Explore | `/tmp/wba-v2-ui8-explore-1280.png` | Release-aware scenario URL resolved the county and displayed map/table equivalents. |
| County ambiguity at 320 px | `/tmp/wba-v2-ui8-explore-320-cook.png` | Keyboard entry of `Cook`, then Enter, retained the committed FIPS `31109` and exposed explicit IL and GA choices; document width equaled 320 px. |
| Contract ticket | `/tmp/wba-v2-ui8-contract.png` | A put with strike 62 computed three scenario paths, physical expected payout `10.333333333333334`, and positive-payout probability `0.3333333333333333`; absent market/station load stayed unavailable. |
| Research nested route | `/tmp/wba-v2-ui8-research.png` | `/research/index.html` loaded the evidence library without adding a second `research` path segment. |
| Portfolio supplied books | `/tmp/wba-v2-ui8-portfolio-underwriter.png` | Regional heating, multi-location cooling, and underwriter capped-claim books each completed Worker ES optimization. Fixture outputs were expected shortfall 12 and deterministic cost 2. |
| Decision record | Browser accessibility tree after Worker completion | An accepted decision included a `decision:<sha256>` identity and enabled JSON-record and Markdown-memo exports. JSON restore validates the identity before accepting the result, without recalculation. |
| Text zoom | `/tmp/wba-v2-ui8-portfolio-200.png` | At 200% browser text zoom, `documentElement.scrollWidth === innerWidth` (1280 px). The holdings editor and result table retain their own horizontal scroll regions. |

Focused automated checks: `uv run pytest tests/site/test_v2_state.py -q` (3 passed), `uv run ruff check apps/site/js tests/site/test_v2_state.py`, `node --check apps/site/js/pages/portfolio.js`, and a Node CSV parser smoke test covering numeric budget and unit-cost preservation.

## Pending reseal

The CSV numeric-field patch is in source and passed the Node smoke test. Its
browser upload-and-optimize check could not be automated: the browser agent
stalled and Chrome's file chooser rejected `setFiles` as `Not allowed`.
The release-pinned V9 fixture nevertheless passed a direct canonical-envelope
integration smoke: its county and station ScenarioMatrix envelopes compiled a
CSV-equivalent put holding through `compileHoldingsProblem`; the resulting
finite problem preserved a `unit_cost` and deterministic cost of 20.

## Sealed representative-real preflight

The final UI seal is `build/releases/v2-real-ui-preflight-6` at
`release:acd0c0a3a8f4dfea6aafe43db708e2509b91f188badd5485e604f479fa991aa0`,
served locally at `http://127.0.0.1:8780`. Its scope is
`representative_real_ui`: seven counties and 2,000 public paths. It is not a
national release. The computational journeys below were run on the same
representative source in sealed preflight-4, then the final preflight-6 seal
validated the responsive repair.

| Journey | Outcome |
| --- | --- |
| Contract ticket and seasonal semantics | Monthly, declared option-on-strip, and sum-of-monthly structures calculated from 2,000 aligned paths. The contract page showed the committed 2027 window, physical payout and station-linear residual distributions, with market/assumed fields remaining unavailable. |
| Contract to Portfolio claim | The carried Contract Lab call was appended to a selected regional book as a `contract_payoff` claim with the exact source scenario set, member entity, payoff DSL, and direction 1. It then completed worker optimization; no hedge was created by the action. |
| Three supplied books | Regional heating, multi-location cooling, and underwriter capped claim each completed browser-worker ES optimization and produced accepted `decision:<sha256>` records. |
| Candidate and cost controls | Removing a selected candidate disabled record/memo export until recalculation; a new accepted record was produced after reoptimization. |
| CSV, export, restore | A locally supplied full-schema CSV mapped three rows without conversion or location dropping and optimized. A downloaded accepted JSON record was uploaded after reload and restored only after its identity validated. The compact producer CSV was rejected because it lacks the UI CSV schema's required budget and hedge columns; no values were guessed. |
| Scenario Room | Historical rows displayed frozen gross loss, hedge payoff, cost, and total loss with its non-predictive warning. Uniform-cold stress displayed null-weight stress semantics and no predictive risk claim. |
| Responsive and keyboard | At 320, 390, 768, and 1280 px, `scrollWidth === innerWidth`; focus starts at Skip to content. At device scale 2, keyboard focus remained visible. |

Screenshots inspected: `/tmp/wba-real-preflight-qa/preflight2-contract-monthly-result.png`,
`/tmp/wba-real-preflight-qa/preflight2-contract-strip.png`,
`/tmp/wba-real-preflight-qa/preflight2-contract-sum-monthly.png`,
`/tmp/wba-real-preflight-qa/preflight4-portfolio-candidate-optimized.png`,
and `/tmp/wba-real-preflight-qa/preflight6-portfolio-320.png`.

Focused source checks: `node --input-type=module --check` for V2 state,
Contract, Portfolio, and app modules; `uv run pytest tests/site/test_v2_state.py -q`
(3 passed). The sealed builder completed successfully for preflight-6.

## Binary-wire representative preflight

`build/releases/v2-real-ui-preflight-7` was sealed at
`release:ca0f01029fdac1696c3416fbbb34ac5d7cfcf85731b7600fd61ebef14f01ffbf`
(scope `representative_real_ui`, not national) and served at
`http://127.0.0.1:8781`.

The browser payload client decoded the float32 binary-wire county matrix into
an identified `2000 × 14` values matrix: ScenarioSet
`sha256:38e2708d2a7e5372a39e5ce7aca29a2984ac41550d6f69a86c09e12c1a0e8503`.
The client removed the transport encoding after decode and restored the source
provenance IDs `sha256:r2j-national` and `sha256:r01-corrected` from the
release source group.

Contract Lab calculated its 2,000-path monthly ticket; Portfolio completed
both supplied-book and full-schema CSV worker optimizations; the downloaded
CSV decision restored after its exact decision identity verified. Scenario
Room displayed the null-weight uniform-cold stress as descriptive only. Durable
artifacts: `docs/v2/ui-evidence/preflight7-contract.png`,
`preflight7-portfolio-worker.png`, `preflight7-csv-worker.png`,
`preflight7-decision-restored.png`, and `preflight7-scenario-room-stress.png`.
