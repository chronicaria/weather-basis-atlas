# Common scenarios

V2 portfolio arithmetic uses a `ScenarioSet` whose ordered IDs are the join key. A `ScenarioMatrix` may be combined only when its parent and ordered scenario IDs match exactly. A sorted `MarginalDistribution` is display/pricing data and cannot enter aligned portfolio arithmetic.

The preliminary research configuration is `common-year-trend-bootstrap-v1`: valuation date 2026-07-01, one global July 2026--June 2027 horizon, 10,000 offline paths and a deterministic 2,000-path public slice. It is a candidate for B20, not a national acceptance decision. The public release store serves lazy county chunks with all 14 retained HDD/CDD pair columns and one fixed scenario coordinate.

`build_historical_common_years` is an observed, complete July--June replay with equal empirical weights. `build_trend_bootstrap` is separately labelled physical-predictive: it resamples one shared daily moving-block sequence across all requested locations, then applies a documented per-location linear calendar-year adjustment. It must never be labelled observed history.

`r2j_common_horizon` applies one shared innovation-block sequence to all locations and all dates in the horizon. The cheap R04 candidate, `rank_coupled_marginals`, uses a whole-vector historical rank template across all monthly entities. It preserves index-level dependence and zero atoms but has **monthly-index-only** support; it cannot make daily paths or establish strip identities.

`marginal_diagnostics` and `dependence_diagnostics` produce separate descriptive evidence for B20 holdouts: per-index mean/scale/quantile differences, then covariance and upper-tail co-occurrence differences. They do not choose a generator, and they must not be run as an in-sample rank-recovery selection rule.

`build_from_frozen(root, out, research, county_ids=None, paths=None)` is the bounded source-panel artifact adapter. It builds all requested counties and the frozen station panel under one plan, writes 14-pair county/station matrices, two audit daily paths, and a manifest with explicit observed-history support or its failure reason. It is marked representative-only. The registered R04 protocol is [`config/research/r04-common-scenarios.yaml`](../../config/research/r04-common-scenarios.yaml); it requires chronological holdouts, separate marginal/joint scoring, and wall/RSS measurement before a production recommendation.

Missing county or pair support raises an explicit error. The engine never removes an unavailable holding and renormalizes the rest. Daily HDD/CDD matrices are reduced from the same temperature path, so `CDD - HDD = T - 65` each day, and monthly components can be checked against strips where their definitions match.
