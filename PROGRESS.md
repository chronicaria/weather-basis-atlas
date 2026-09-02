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
