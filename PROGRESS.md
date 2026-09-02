# Build progress

## 2026-09-02 — Phase 0

- Created the Python 3.12 `weather_basis` package and the plan-prescribed repository layout.
- Active work: core utilities, donor migration, geography, panels, and tests.
- Donor: `/Users/andrewpark/Desktop/Code/WeatherDerivativePricing` (read-only).

## 2026-09-02 — Phases 0–3 complete

- Migrated and re-hashed 906 frozen TAVG monthly files (1,812 raw and
  version files checked). Manifest SHA-256:
  `1fc446b3a0648bad118e7537da98469fe2080eb02e5ecc67e1fc75a9e7ad70a7`.
- Built the 27,575 × 3,107 county panel, 18-station QC panel, all 14 county
  and station index panels, and the rolling-origin atlas.
- Atlas output contains 43,498 county/pair rows and 565,474
  county/pair/station rows. All 14 pair bootstraps use B = 1,000 and seed
  20260901.
- HDD-01 classifies 85.1% of counties as hedgeable under the pre-registered
  joint point/lower-bound rule; CDD-07 classifies 52.4%. These values are
  generated from `results/atlas/headline.json`, not template literals.
- Gates 0, 1, 2, and 3 pass locally after the observed-vintage decisions in
  `docs/decisions/` were recorded.

## 2026-09-02 — Phases 4–6 complete

- Ran the production daily R2/R2j fit for 3,107 counties and 18 station series,
  then wrote aligned and sorted 10,000-draw distributions for all 14 contracts.
  The simulation completed in 256 seconds with a measured maximum resident set
  below the 12 GB ceiling.
- Ran all 32 tournament origins for every contract with 2,000 draws, producing
  14 score partitions, 686 state/pair selection rows, origin calibration, and
  the pre-registered power output. The historical tournament's R2/R2j rows use
  the documented annual-index residual fallback; site pricing uses the full
  daily R2j path.
- The joint diagnostic favored aligned R2j draws in 243 of 252 evaluated rows
  and had lower aggregate CRPS than independently paired draws. The nine
  observed exceptions are recorded in decision 0004 rather than hidden.
- Built 869,960 coherent option indications for 3,107 counties and 14
  contracts. The coherence gate reported zero violations.
- Built and validated the static release: 3,107 gzip county payloads, 14
  contract summaries, 160,487,917 total bytes, and a largest county payload of
  50,383 bytes. The initial production build exposed and prompted removal of a
  pandas metadata deep-copy bottleneck; subsequent full builds take about two
  minutes.
- Browser smoke and an independent agent-browser walkthrough covered desktop
  and 375 px mobile layouts, county search, contract and layer changes, gzip
  decoding, quote display, local-only requests, and console/page errors.
- Gates 0 through 6 pass on the final corrected production artifacts.
- Public hosting and Gate 7 remain human-controlled because choosing an account
  and making the site externally visible require H-3 authorization.
