# V2 interface revision 1

Canonical schema version is `2.0`; dataclasses under `src/weather_basis/schemas/` are authoritative. `StrictRecord.from_dict` rejects unknown fields, missing explicit versions, incompatible types, and nonfinite JSON. JSON Schema under `schemas/v2/` is generated/documented from these records.

Scientific content IDs use strict canonical JSON and exclude execution settings. Full source commit belongs to provenance; producer fingerprints identify relevant code. Seeds use `v2-seed-1`. FIPS is a five-character string. Money is USD, positive loss harms the customer, long payoff benefits the customer, deterministic costs enter once.

The accepted aligned boundary is `ScenarioSet` plus `ScenarioMatrix(parent_scenario_set_id, scenario_ids, entity_ids, values, units)`. Matrices contain scenario rows and entity columns; joins require the identical ordered scenario IDs and parent. `select` fails for absent entities. Display marginals have a separate type. Missing/null probabilities are accepted only for labelled stress sets and never predictive optimization.

The portfolio boundary is `PortfolioProblem(losses, payoffs, scenario_ids, weights, candidate_ids, cost_model, constraints)` with strict validation by the portfolio adapter. Cash flows and risk accumulate in float64. Both browser and Python consume identical finite-matrix problems and golden vectors. Browser public limits: six locations, 24 exposure rows, 39 hedge columns, 12 months, 2,000 common paths. Offline research initially uses 10,000 paths.

State fields: schema/release, route and selected research record, committed FIPS and comparison FIPS, index/month, contract year/window, valuation as-of, payoff family/direction/strike/cap/multiplier, strategy and versioned assumptions. Private imported books stay local and restore from an exported decision manifest, not URLs. Unknown releases fail explicitly or open the V1 archive.

One stage namespace: `wba v2 plan/run/verify/bench/release/serve`. Plan freezes scientific inputs and coordinates. Worker/memory overrides may change execution only. Producers do not parse arbitrary YAML. New source acquisition is never implicit.
