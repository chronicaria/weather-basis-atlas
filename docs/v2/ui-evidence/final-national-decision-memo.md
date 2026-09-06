# Portfolio decision memo

## Question

optimize es local weather-basis portfolio

## Identity and replay boundary

Decision: `decision:c6658673f59262d3f9b82de78e0980abec7f3514aaea824f70d9d5b1fff4d47d`

Release: `release:6ef583abd964e2d0d9ad0b560bb0df212da2d298d262e633d501b17fa3ad3b20` · Scenario set: `sha256:38e2708d2a7e5372a39e5ce7aca29a2984ac41550d6f69a86c09e12c1a0e8503`

Scenario sample: 2000 paths; units USD; lots continuous.

## Holdings and contracts

- custom-heating-omaha: heating_shortfall on 31055:HDD-01
- custom-heating-lincoln: heating_shortfall on 31109:HDD-01
- custom-heating-grand-island: heating_shortfall on 31079:HDD-01

Candidate contracts:
- candidate-contract:2c5fee979986dd0fa67592b7181478ccbd16375232ebe4d46678c9244a5f7f09: {"candidate_id":"candidate-contract:2c5fee979986dd0fa67592b7181478ccbd16375232ebe4d46678c9244a5f7f09","contract_spec_id":"illustrative-station-option-20-usd-per-degree-day-v1","loss_kind":"heating_shortfall","multiplier_usd_per_degree_day":20,"payoff":"put","station_entity_id":"USW00014935:HDD-01","strike":1205.4029989242554}
- candidate-contract:3d953e1d3a17a5fdf40b29f845c04c28db0897407b27a1fce5c9b9afc7080a48: {"candidate_id":"candidate-contract:3d953e1d3a17a5fdf40b29f845c04c28db0897407b27a1fce5c9b9afc7080a48","contract_spec_id":"illustrative-station-option-20-usd-per-degree-day-v1","loss_kind":"heating_shortfall","multiplier_usd_per_degree_day":20,"payoff":"put","station_entity_id":"USW00014939:HDD-01","strike":1247.1719961166382}
- candidate-contract:9738719d6e015458491639104b845937165109c1649a31c51b933d2d9ea6de08: {"candidate_id":"candidate-contract:9738719d6e015458491639104b845937165109c1649a31c51b933d2d9ea6de08","contract_spec_id":"illustrative-station-option-20-usd-per-degree-day-v1","loss_kind":"heating_shortfall","multiplier_usd_per_degree_day":20,"payoff":"put","station_entity_id":"USW00014942:HDD-01","strike":1284.7289953231812}

## Baseline versus accepted decision

| Measure | Zero-position baseline | Accepted decision |
| --- | ---: | ---: |
| Expected shortfall | 95303.58836746214 | 57990.65302315827 |
| Variance | 988025644.2930866 | 258512028.93713516 |
| Deterministic cost | 0 | 29950.351067290932 |

Positions: `[9.93234,7.00365,0]`

## Constraints and feasibility

Objective: es; ES target: Unavailable; cash budget: Unavailable.

Binding constraints: lower_bounds.

Constraint residuals: `{"lower_bounds":0,"upper_bounds":null}`

Status: optimal; reason: none.

## Adverse sampled paths

- sha256:ff2d3-r2j-01617: residual loss 97679.159064181
- sha256:ff2d3-r2j-01649: residual loss 88917.37696657357
- sha256:ff2d3-r2j-01101: residual loss 87746.60378971811

## Assumptions and provenance

Cost assumptions: `{"contract_fee_id":"illustrative-20-usd-per-contract-fee-v1","contract_fee_usd":20,"cost_profile_id":"illustrative-physical-expected-option-payout-plus-20-usd-contract-fee-v1","description":"Illustrative physical premium equals the scenario-weighted expected option payout per declared 20 USD/degree-day contract plus a fixed 20 USD contract fee. It is not an observed or executable market quote.","market_quote_status":"unavailable_no_market_quote_asserted","premium_model_id":"illustrative-physical-expected-option-payout-v1","zero_cost_sensitivity_id":"zero-cost-sensitivity-v1"}`

Sources: a9e833ab702b6c9933de0249ace0e4671f9cbd23b2c3399e8550fcedf2e886cf, aa8c0016df38eb91a1c9b3a7acc12e0cb0d8614d0c5d9d08c4067b0c98816924, 200d9ba7f824b8a598229f720a189c84d2688ba67fd46d21db8c5de811381392, 720a233672a9b8c2c9d17d35c0ca2b97c0b52d15dee1b575a54628890a071161, 7c445120c7bda71752ad4fbb68467e87d4cac41313c0fb865263e40f48d20045, 9ab6ee41c488452cc8f54b49e5f2e78f98a651c4afa8290487f44a235b80786c, 7ea8961e3964dbb4ea7858c9cc693595245bb1fdf6436d3c988954def57906d6, ef820d68eb74a7e67f943068cc1210d321c453182028ede01ceb6fb65eb417c3, 6abdba54d9c04c9cd45f726eb6a516daab4481eddc445f694094093ba6413b91, 18f9fb5843136bcd93854d1cee968c87154894871f6c0f4c34bee63d605256da, 2b82c3c7c597ea936fbe4a69931156fa7241ec10b74e5c40acd1ed45a5adfd74, 989f45658c1af0066efe793616c7c6ba09121100897641caea399345d921b4f2, 786574ea036ecda8ebe6780debeb5e7388a64c276f01fe5a952e6be1813f53dc, c48e8a133c2de7be0af2b1ea7d11e439b363015ab94dc7d33d6c82130aac8ea7, 1e41312f3c81b66b3489326a85df122856be451c763f7b47a80a62a874d64b02, a7316ba0c0f120fbfe3b9c7dff6b20f500d39f6a8ff3b377a985b32450539941, 4dea04873623a724f46abca322bec8a92b6cc7515e8a37dbd391475696b8e87d, 9c3cf355aeb4c295e9f81b44a90c9aaddbf57be734c51c50922f59f10c0b7d27, b331193f83d87a00360b46eebc59b39450059a835f302726bbea1cd1a006a48e, 9d25e46bc100597ef3d6fd7b593446885a925305d88b818ba6fd74d9f283c013, 20f0b086ac9a113298d9d86ab73010f3586687ea7f1d0a7b0806babf720519e6, 087199b78f1bb79682fa8f52155e053cd2bb35b6386424a73dc749358c2b3b93, e5a577ee44d515ef5cf0d02059f70ff6ea403088799b02227c27f7ed3fe7a7dc, 24e8a526606d11d3946314e2e70ae0327d71467e6241620afd0d504bc0284085, 469517ae312c2143f44467feb46a687f93c14f7370f533e6d62f815f5112daad, a7e1fc7149234831ac587dcbe1b6f7f398a416cf1334c63c4a3aa8295dbd3671, 29442496a3db5fc65e602d874bed7718c48df62b20d4fbf531338756a4d4d51b, 3da51d68f98404758ba999ec81aa316cb4e0d61363df645bf8c6d9856006ea9f, babf12da8331c2836ba664797b173f40e4bdccd06c294ef0a7b2126dd9f5bb39, 8337a5be1418f2e2035949df1d2f1b221385c5f8e7355784c760931faf1f5bc8, 18c1e6f6ba47ea2bddb402a5be17ca927f40d89a669e9242f0ffc3998c21a1c2, eb412c87bc828c7547ebacc609f900836cc8f617451aad5110536421db8e41b5, 25bd57f3c0b083b525370b78a9f4400bae64a6d5a05bb4771fa3bb0faa4b61f6, 44f96008d4e190778a55c7b4085d195e0452369cd1c4dc371da65cb3d10ac4fc, 7bf83ee857656372e77bf7f0abd081b5056c9596364ac94d5c3877e5560f854a, feb0cb9051f4a3e61ffd5696b7f82a00f605bdf595f9f6afa670e300ca49056a, b12a6e5f46d018020abf4ec859e51ee1ff3ec927fbcf45e5872479731a9e2245, 2fccc17a2112285c1a4817e505814222e013428c16aeee178362be351e5a3832, c8c978d2b60802182c58c69969a9aee94224798baa0273b1c392a40dc1950210, ae14f9001ac0eb4c332c4b2008cbccc01bf5d186b4a53f2794ec24fe503fe2b0, a5e5c3e1464ce317e13f7e6c494e326bc0f9db30e62eb9725ad6d2f8510ec43d, dec4cfbfb4877822a1b134318479af2cc9274607e13a412cb4069f8a3d35adf3, 08c83168fd868a012487d85f84f26dbbe974b088490bd15555d2f798677a693d, sha256:45a9f8c29ab9a726c46788a52e8fdb6d9a55eabd891efa6076a45f8817d8b996, sha256:1991fc9542d7b79cfd6b78e24a2b6ceb7c2ddfbf93ef278b4ba4797a6498c8b1, sha256:609279ea71fa209a3e98c62e67bdd6f867b5bbafb2bf879d2a4b98d0a84d40ea, sha256:2b645416554294cd13676d1f7c6fec60e296d911f6ec9144d29f80ddaa9d9b9f, sha256:f17906cddeec015810e0ac65c8f0e445959499a986e7a099ed2ed555f2fbaa06

Model specifications: R2j, sha256:c20ba74caac1e6ac2130de339c94e1b3a25cd724a399f4d557ec03bbd92e4b45, r2j-raw-residual-before-ar-v1

Object identities: object:e7bd53334df530b9ac4cdc467065ab9761fcf52280db37ff6302f9b8fc9a551c, object:b34545d9f345154585e35788b6643c00b07255f1e4a60a42110c88f0d661a9eb, object:ffedd40d39fac3f2dfb87260efb93d79fb5637261f21c18516738b9e17bf7a04, object:55a40ebf4e9545d18627ef0447b2d1aef82729378a275cb55fa75a65bd19828e, object:4e00e152e0a6c60e0fcf6a506b00f47881fcde7f25dce239b8fea22f21799f81

Browser calculation from the release-pinned scenario inputs; no unpublished market or weather claim is added.

## Reproduction

Save the exported JSON as `decision.json`, then run:

`uv run python scripts/replay_portfolio_decision.py decision.json`

To inspect the same accepted record in the browser, use Portfolio Lab → Import local book, accepted decision, or CSV, choose the JSON file, and confirm the displayed decision identity before exporting again.
