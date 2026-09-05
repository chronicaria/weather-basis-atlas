# Weather Basis Atlas

Weather Basis Atlas is a reproducible county-to-weather-station basis-risk
research instrument. V2 candidate validation is underway; the public release
remains V1 until a V2 candidate is accepted, sealed, and deployed.

The current V2 national evaluation ledger contains 43,498 county/pair records:
43,148 evaluable records, 350 unavailable records, and 6,355 records where the
prior best is better. These are ledger counts, not a release headline or a
general performance claim.

The current V2 plan has valuation as-of 2026-07-01 and a 2026-05-31 observation
cutoff. It uses one joint 10,000-path offline scenario set and its deterministic
2,000-path public prefix. The three supplied portfolio books retain declared
constraints and local-CSV inputs; physical pricing, assumed loads, and absent
market observations remain distinct regimes. The 2023--2025 outcomes have
already been consumed for development and are exploratory evidence.

## What is in this repository

- `data/` contains manifests, metadata, contracts, and reproducible input
  records. Raw source files are versioned separately from derived panels.
- `results/atlas/` is retained V1 atlas evidence. `results/v2/` contains V2
  candidate artifacts and validation ledgers.
- `results/indices/` contains monthly county and station index panels.
- `results/qc/` records panel, station, geography, and vintage checks.
- `docs/site/` contains methodological, provenance, model-card, and Nebraska
  case-study copy rendered into the static site.
- `site/` is the locally built static release artifact; its county payloads
  are deterministic gzip files.

## Definitions

For a daily mean temperature `tbar` in degrees Fahrenheit, heating degree days
are `max(65 − tbar, 0)` and cooling degree days are `max(tbar − 65, 0)`.
Monthly indexes sum those daily values. County `tbar` is daily TAVG; station
`tbar` is the arithmetic mean of quality-controlled integer-F TMAX and TMIN.
This station calculation reproduces the public index convention, but is not
settlement data.

The primary outcome is held-out hedge effectiveness: one minus the hedged
residual sum of squares divided by the comparable unhedged anomaly sum of
squares. A county is labelled hedgeable only under the jointly pre-registered
point-in-time effectiveness and bootstrap-lower-bound rule. Definitions,
selection, and uncertainty procedures are fixed in
[the pre-registration](docs/preregistration.md).

## V1 archive workflow

```bash
uv sync --frozen
uv run wba data verify
uv run wba indices build
uv run wba atlas run
uv run wba atlas headline
uv run wba site build
uv run wba site check
```

These commands reproduce the retained V1 workflow. The V2 candidate commands,
artifact locators, and release requirements are in [docs/v2](docs/v2/).

## V2 sealed release commands

After a national candidate is accepted and its lock exists, build a fresh
bundle and verify it before packaging a pinned GitHub Release asset:

```bash
uv run wba v2 release build --lock config/releases/v2-candidate.lock.json --out build/releases/v2-candidate
uv run wba v2 release verify --bundle build/releases/v2-candidate
uv run wba v2 release inspect --bundle build/releases/v2-candidate
uv run python scripts/package_release.py --bundle build/releases/v2-candidate --out build/release-assets/weather-basis-atlas-v2.tar.gz
```

Recovery verifies a prior sealed bundle before copying it to an explicit target:

```bash
uv run wba v2 release rollback --bundle build/releases/v2-prior --target build/recovery/v2-prior
```

The manual Pages workflow accepts only a pinned GitHub Release asset URL, its
SHA-256, and its embedded release ID. It does not deploy the tracked `site/`
directory. See [the V2 release runbook](docs/v2/release.md).

## Source and release discipline

Input URLs, retrieval metadata, and cryptographic digests are retained under
`data/manifests/`; each derived stage has a result manifest with configuration,
seed, software revision, and output identity. The release uses frozen source
vintages and a snapshot-based reproduction route rather than silently
refreshing regenerated upstream observations.

Code is MIT licensed. Data retain their source terms as recorded in the
contract and input manifests.

## Interpretation boundary

Research and education only. Outputs are model estimates, not executable
quotes, offers, insurance, investment advice, or a promise of future hedge
performance. The project is not affiliated with, endorsed by, or sponsored by
CME Group or Speedwell/Xweather. Station names identify public NOAA stations;
no exchange price data are reproduced.
