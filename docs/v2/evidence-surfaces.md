# Evidence surfaces

`weather_basis.research.evidence_surfaces` projects readable Research and
Scenario Room records from frozen local inputs. It does not start a national
job, retrieve a new source, fit weather, or turn a stress path into a
probabilistic forecast.

`evidence_envelopes()` returns typed `ResultEnvelope` records for the
glossary, methods, source support, holdout access ledger, limitations,
measured R04 performance, and validation topology. Each record carries hashes
of the frozen reports and source-vintage lock. R02, R03, R04, R05 and the
Nebraska case remain separate evidence tiers; the builder does not turn a
bounded result into a national conclusion.

`scenario_room_envelopes()` uses exactly seven county locations (`31055`,
`31109`, `31079`, `31111`, `31157`, `06037`, `36061`) and all frozen station
series. Its source windows are registered before any hedge comparison:
2012-07–2013-06, 2014-07–2015-06, and 2021-07–2022-06. A window must contain
all 365 daily dates and finite data for every location. An incomplete window
is reported with its reason and is never replaced by another year.

Available historical records carry an actual `ScenarioSet`, an aligned daily
temperature cube (`scenario_id × local_date × location_id`, `degF`), and the
corresponding 14-pair `ScenarioMatrix` of monthly HDD/CDD indexes. The current
frozen panel accepts 2013 and 2015; 2022 is retained in `unavailable_windows`
when a station has missing daily support.

The three stress records reuse the first complete registered historical window:
uniform +3 F, uniform -3 F, and +3 F for the five Nebraska county locations.
They recompute all monthly HDD/CDD columns. Their `ScenarioSet` type is
`stress`, `probability_weights` is `null`, and the payload states that no
predictive expected shortfall or weather fit is available. Holdings, positions,
costs, and risk decompositions stay in the accepted `book:*` envelopes so the
UI does not confuse a weather-path surface with a portfolio result.
