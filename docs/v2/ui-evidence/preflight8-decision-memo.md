# Portfolio decision memo

## Question

optimize es local weather-basis portfolio

## Identity and replay boundary

Decision: `decision:44fb5f0715df168dbdda03754e5ee1c2594d6aded05ee893ebb8ce4c043fdf98`

Release: `release:7224ce362c35b3da4eae71819cd7cbd54442bd4c466dbaa4af801260a82ce63e` · Scenario set: `sha256:38e2708d2a7e5372a39e5ce7aca29a2984ac41550d6f69a86c09e12c1a0e8503`

Scenario sample: 2000 paths; units USD; lots continuous.

## Holdings and contracts

- heating-omaha: exposure on 31055:HDD-01
- heating-lincoln: exposure on 31109:HDD-01
- heating-grand-island: exposure on 31079:HDD-01

Candidate contracts:
- candidate-contract:2c5fee979986dd0fa67592b7181478ccbd16375232ebe4d46678c9244a5f7f09: {"candidate_id":"candidate-contract:2c5fee979986dd0fa67592b7181478ccbd16375232ebe4d46678c9244a5f7f09","contract_spec_id":"illustrative-station-option-20-usd-per-degree-day-v1","loss_kind":"heating_shortfall","multiplier_usd_per_degree_day":20,"payoff":"put","station_entity_id":"USW00014935:HDD-01","strike":1205.4029989242554}
- candidate-contract:3d953e1d3a17a5fdf40b29f845c04c28db0897407b27a1fce5c9b9afc7080a48: {"candidate_id":"candidate-contract:3d953e1d3a17a5fdf40b29f845c04c28db0897407b27a1fce5c9b9afc7080a48","contract_spec_id":"illustrative-station-option-20-usd-per-degree-day-v1","loss_kind":"heating_shortfall","multiplier_usd_per_degree_day":20,"payoff":"put","station_entity_id":"USW00014939:HDD-01","strike":1247.1719961166382}
- candidate-contract:9738719d6e015458491639104b845937165109c1649a31c51b933d2d9ea6de08: {"candidate_id":"candidate-contract:9738719d6e015458491639104b845937165109c1649a31c51b933d2d9ea6de08","contract_spec_id":"illustrative-station-option-20-usd-per-degree-day-v1","loss_kind":"heating_shortfall","multiplier_usd_per_degree_day":20,"payoff":"put","station_entity_id":"USW00014942:HDD-01","strike":1284.7289953231812}

## Baseline versus accepted decision

| Measure | Zero-position baseline | Accepted decision |
| --- | ---: | ---: |
| Expected shortfall | 92392.18611564636 | 56155.88702717324 |
| Variance | 928377805.5922774 | 242928197.85759896 |
| Deterministic cost | 0 | 29054.34022598095 |

Positions: `[9.72532,6.69246,0]`

## Constraints and feasibility

Objective: es; ES target: Unavailable; cash budget: Unavailable.

Binding constraints: lower_bounds.

Constraint residuals: `{"lower_bounds":0,"upper_bounds":null}`

Status: optimal; reason: none.

## Adverse sampled paths

- sha256:ff2d3-r2j-01617: residual loss 94963.01583258534
- sha256:ff2d3-r2j-01649: residual loss 85869.59055836659
- sha256:ff2d3-r2j-01101: residual loss 85079.73655309316

## Assumptions and provenance

Cost assumptions: `{"contract_fee_id":"illustrative-20-usd-per-contract-fee-v1","contract_fee_usd":20,"cost_profile_id":"illustrative-physical-expected-option-payout-plus-20-usd-contract-fee-v1","description":"Illustrative physical premium equals the scenario-weighted expected option payout per one USD/degree-day contract plus a fixed 20 USD contract fee. It is not an observed or executable market quote.","market_quote_status":"unavailable_no_market_quote_asserted","premium_model_id":"illustrative-physical-expected-option-payout-v1","zero_cost_sensitivity_id":"zero-cost-sensitivity-v1"}`

Sources: sha256:real-ui-preflight-source, sha256:r2j-national, sha256:r01-corrected

Model specifications: R2j, sha256:e7e22c2f2c2514a21cdb779b9de4f33b731c4ed5b6cd5c2b9962ca6b95d171b8, r2j-raw-residual-before-ar-v1

Object identities: object:857ebe7856fa300743fa6cf6e9c6eec272c606b17026c70e0fb6ce0802a5df10, object:d17577e8f490d935df580f638939139e103b33b721824b1e5f13dc6d33886ac1, object:f5440e8a1d98238fafd551d57158bd192735cb3abba0c7f2ff2df3994c696133, object:ba653d39c92ef7785019c76229d5205981f6dc3b8da436c2c51341c97724740f, object:88dac607c34b6d877462041c536b274628bd7d7f36635523410b5f8ea9910a54

Browser calculation from the release-pinned scenario inputs; no unpublished market or weather claim is added.

## Reproduction

Save the exported JSON as `decision.json`, then run:

`uv run python scripts/replay_portfolio_decision.py decision.json`

To inspect the same accepted record in the browser, use Portfolio Lab → Import local book, accepted decision, or CSV, choose the JSON file, and confirm the displayed decision identity before exporting again.
