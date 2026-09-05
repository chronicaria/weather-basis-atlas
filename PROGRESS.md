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
  contract summaries, 160,489,750 total bytes, and a largest county payload of
  50,383 bytes. The initial production build exposed and prompted removal of a
  pandas metadata deep-copy bottleneck; subsequent full builds take about two
  minutes.
- Browser smoke and an independent agent-browser walkthrough covered desktop
  and 375 px mobile layouts, county search, contract and layer changes, gzip
  decoding, quote display, local-only requests, and console/page errors.
- Gates 0 through 6 pass on the final corrected production artifacts.
- Lifted the 2023–2025 tournament holdout exactly once after selection was
  frozen. Twelve of 14 contract confirmations were non-negative versus R0;
  CDD-06 was -0.29%, CDD-09 was -1.32%, and CDD-10 was strongest at +10.44%.
  The tournament manifest records `holdout_unlocked = true` for this run.
- Public hosting and Gate 7 remain human-controlled because choosing an account
  and making the site externally visible require H-3 authorization.

## 2026-09-04 — Final local release audit and reproduction

- This entry supersedes the provisional Phase 4–6 notes above about an
  annual-index residual fallback and 243 of 252 joint-diagnostic wins. The
  release tournament uses the registered daily rolling R2/R2j path at every
  origin. Its strict joint diagnostic favors R2j in 252 of 252 rows: pooled
  mean CRPS 11.395629 versus 24.775489 for independently paired draws
  (one-sided sign-test p = 1.38e-76).
- A fresh detached checkout of source commit
  `465c25c1d0bf853186dbdcd0916d7b302cadc32d` reproduced from the frozen raw
  snapshot and matched all 48 committed Parquet files byte for byte, plus
  `headline.json`, `pairs.parquet`, and `quotes.parquet`. The complete replay
  took 12:20:53 wall time, including host sleep/clock gaps; the reference
  uninterrupted strict tournament took 7:37:57.
- Snapshot: `/tmp/weather-basis-atlas-2026-06.tar.gz`, 259,675,160 bytes,
  SHA-256 `3d854584795496a320487b4f3e4cabc4b3121a5a57bbf89408790d4dd61963e6`.
- Release outputs: 869,960 quote rows; 50 of 50 recomputed quotes matched with
  maximum absolute error 0; the fixed seed-agreement panel passed 700 of 700;
  and quote coherence reported zero gate violations. The site contains 3,107
  county payloads and 14 pair summaries, totals 196,229,318 logical bytes, and
  has a largest gzipped county payload of 62,839 bytes. The working tree is
  approximately 9.5 GiB; Git object storage is approximately 1.1 GiB.
- Rendered release headline: For HDD January, 15% of CONUS counties (12% of
  population) have no point-in-time-selected CME hedge whose out-of-sample
  hedge effectiveness reaches the pre-registered threshold with the required
  bootstrap lower bound; in 38% of counties the best station is not the
  nearest (median gain -0.02 HE). For CDD July, 48% of CONUS counties (42% of
  population) have no point-in-time-selected CME hedge whose out-of-sample
  hedge effectiveness reaches the pre-registered threshold with the required
  bootstrap lower bound; in 46% of counties the best station is not the
  nearest (median gain -0.07 HE).
- Decision records: 0001 auxiliary-temperature vintage drift; 0002 observed
  station roundtrip and vendor count; 0003 degenerate-index hedge
  effectiveness; 0004 joint-diagnostic observed exceptions; 0005 county
  payload measured cap; 0006 serial rolling model fits; 0007 joint-diagnostic
  short-record eligibility; 0008 non-artifact CLI manifest scope.
- Known limitations (copied from the model card):
  - The county temperature layer has the homogenization and vintage look-ahead
    described above; it is not a historical real-time operational feed.
  - GHCN-Daily has reporting gaps, quality flags, station changes, and archive
    lag. The quality-control rule reduces but cannot erase those issues.
  - County exposure is an area-average temperature index, which can differ
    from a policyholder, crop, facility, or settlement location exposure.
  - The analysis is historical and climatological. It omits live weather
    forecasts, financing, transaction constraints beyond the stated
    convention, and actual market microstructure.
  - The model is evaluated on finite historical samples. Bootstrap intervals
    and diagnostics describe the procedure's sampling variation, not a
    guarantee.
- Gate status: Gates 0–6 were green locally before this final replay and will
  be re-attested on the final clean tree. Gate 7's local reproducibility and
  placeholder checks are satisfied; its live-URL checks await H-3 and public
  deployment.
- Human-only status: H-1 CME browser downloads not supplied (optional for the
  build); H-2 Databento pull not requested (optional); H-3 GitHub account or
  organization unresolved and required for public push/Pages; H-4 walkthrough
  video not supplied (optional).

## 2026-09-04 — Final gate re-attestation

- Gates 0–6 passed again on clean commits dated 2026-09-04. Gate 7 collected
  three tests: its fresh-clone hash-equality test and rendered-release test
  passed; only the live-release test failed because
  `results/manifests/release.json` does not yet exist.
- No local implementation or verification work remains. H-3 must select the
  GitHub account or organization before the public repository, Pages site,
  live smoke evidence, release manifest, and final Gate 7 attestation can be
  created.

## 2026-09-05 — Public release destination selected

- H-3 is resolved: the public repository is owned by the `chronicaria`
  identity at `https://github.com/chronicaria/weather-basis-atlas`.
- GitHub Pages is configured to deploy the committed `site/` artifact through
  GitHub Actions at `https://chronicaria.github.io/weather-basis-atlas/`.
