# V2 data and contract support

This registry freezes the existing V1 inputs. It does not fetch NOAA data,
market data, or settlement records. `config/vintages/v1-frozen.yaml` stores the
input-manifest hashes and `config/contracts/v2-temperature.yaml` stores the
retained contract-document hashes.

| Variable / source | Frozen coverage | Coherent use | QC and availability | Permitted V2 use |
| --- | --- | --- | --- | --- |
| County TAVG / NOAA nClimGrid-Daily | 1951-01 through 2026-06 | Through 2026-06 for TAVG-only work | Retrospective revised snapshot; historic issue-time availability is unknown | County temperature research and physical HDD/CDD index |
| County TMAX / NOAA nClimGrid-Daily | 2023-01 through 2026-06 | Only through 2025-12 with TAVG/TMIN | The 2026 TAVG/TMAX/TMIN mismatch reached about 6.92 F | Bounded auxiliary research only |
| County TMIN / NOAA nClimGrid-Daily | 2023-01 through 2026-06 | Only through 2025-12 with TAVG/TMIN | The 2026 TAVG/TMAX/TMIN mismatch reached about 6.92 F | Bounded auxiliary research only |
| Station TMEAN / NOAA GHCN-Daily | Frozen panel through 2026-06 | Through 2026-06 for station-proxy research | Nonblank Tmax/Tmin Q flags are masked before documented short interior-gap filling; filled and missing states remain explicit | Station proxy HDD/CDD research |
| Station metadata / NOAA HOMR | Frozen 2026-09-02 snapshot | N/A | Parsed metadata are warnings; no parsed break is not evidence of station stability | Metadata-break review |

The station index is calculated as daily `(Tmax + Tmin) / 2`, then transformed
to HDD/CDD, then summed over the period. County TAVG follows a different order:
daily county mean temperature, then degree-day transform, then period sum.
Neither calculation equals an average of gridpoint degree days, official
settlement, or a company's economic loss without a separate loss model.

## Contract evidence and modes

The retained city, product-code, and 14-month calendar tables are hand
transcriptions from the linked CFTC/CME documents. Their local SHA-256 values
are in `data/contracts/README.md` and the V2 registry. Their evidence tier is
`retained_documentary_transcription`; it is not an official settlement tape.

`ContractSpec`, `InstrumentListing`, and `MarketObservation` are separate
records. A specification can be documented while a historical listing is
unknown. No dated instrument master is frozen, so the registry returns
`unknown_historical_listing` with no inferred symbol. No licensed historical
bid, ask, trade, volume, open-interest, or official settlement input is frozen,
so market records are explicitly unavailable rather than zero-valued.

The old second-weekday helper remains a visibly labelled research approximation.
No versioned exchange-business-day holiday calendar is retained, therefore exact
settlement timing and market-execution modes are disabled. A July 1 request for
June resolves to the next June contract. During an active month the window
records observations through the day before valuation and the remaining interval
from the valuation day onward.

## Retained evidence

- `data/contracts/cme_city_universe.csv` — SHA-256 `9c51d584015fbcd417e66f6e5e77cc4e4aa49d1c72e79a6f25b75a5237d45360`.
- `data/contracts/cme_contract_calendar.csv` — SHA-256 `61aec994ed8c828a8e88dd4135748ade23541758f6e5f89697ab2d1f1fec5273`.
- `data/contracts/cme_product_codes.csv` — SHA-256 `07d77777d24737dedcd68ed4a5cf83050291030020d3802d315c4f3ff4a7105d`.
- `config/vintages/v1-frozen.yaml` — source-manifest and panel inventory hashes,
  QC/imputation rules, access class, and unsupported-mode reasons.

The registry must not be used to claim historical tradability, official index
settlement, market pricing, or historical information-time availability.
