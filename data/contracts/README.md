# CME contract facts

These small tables are vendored, hand-transcribed contract metadata. They are not
market data and the package never fetches `cmegroup.com`.

| file | source | document code | retrieval date | table SHA-256 | verified by |
| --- | --- | --- | --- | --- | --- |
| `cme_city_universe.csv` | [CFTC filing](https://www.cftc.gov/sites/default/files/filings/ptc/23/05/ptc0504231410.pdf) | `ptc0504231410.pdf` (Chapter 403) | 2026-09-01 | `9c51d584015fbcd417e66f6e5e77cc4e4aa49d1c72e79a6f25b75a5237d45360` | not yet human-verified |
| `cme_contract_calendar.csv` | Chapter 403, reproduced in the CFTC filing above | `ptc0504231410.pdf` | 2026-09-01 | `61aec994ed8c828a8e88dd4135748ade23541758f6e5f89697ab2d1f1fec5273` | not yet human-verified |
| `cme_strips.csv` | [CFTC filing](https://www.cftc.gov/sites/default/files/filings/ptc/24/05/ptc0523241209.pdf) | `ptc0523241209.pdf` (Chapter 405) | 2026-09-01 | `30c2e41b02a581defb8834987821abaad233319179d5e12f6cefb6b5fdb93aef` | not yet human-verified |
| `cme_product_codes.csv` | CME weather product slate | `PM23WE001/0823` | 2026-09-01 | `07d77777d24737dedcd68ed4a5cf83050291030020d3802d315c4f3ff4a7105d` | not yet human-verified |

Human-only source artifacts belong in `source/`: Chapters 403, 403A and 405, the
product slate, fact card, and a dated Section 24 bulletin. Once present, record a
retrieval date and SHA-256 in `source/SHA256SUMS`; no automated test relies on
those PDFs being present.
