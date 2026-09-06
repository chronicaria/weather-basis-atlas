# Weather Basis Atlas

Weather Basis Atlas is a reproducible temperature-exposure and portfolio research
workbench. [V2 is live](https://chronicaria.github.io/weather-basis-atlas/), with
Explore, Compare, Contract Lab, Portfolio Lab, Scenario Room and Research.

The national study retains all 3,107 counties × 14 index/month pairs: 43,148
records are evaluable and 350 unavailable. Prior-best selection beats nearest
in 6,355 evaluable records; that is a matched historical finding, not a universal
performance claim. Current as-of station selection is a separate object.

One joint 10,000-path offline scenario set supplies an exact 2,000-path public
prefix. Three illustrative books and bounded local CSV books support actual
browser optimization and decision JSON, memo and CSV export/restore. Physical
payouts, assumed risk charges and unavailable market observations remain
separate. The valuation convention is July 1, 2026, with May 31 observation
cutoff and an explicitly frozen retrospective vintage. Outcomes from 2023–2025
are consumed development evidence.

Start with the [handover](docs/v2/handover.md), [acceptance register](docs/v2/acceptance.md),
[quickstart](docs/v2/quickstart.md) and [release/recovery runbook](docs/v2/release.md).

## What is in this repository

- `data/` contains manifests, metadata, contracts, and reproducible input
  records. Raw source files are versioned separately from derived panels.
- `results/atlas/` is retained V1 atlas evidence. `results/v2/` contains V2
  accepted artifacts, explicit superseded candidates and validation ledgers.
- `results/indices/` contains monthly county and station index panels.
- `results/qc/` records panel, station, geography, and vintage checks.
- `docs/site/` contains methodological, provenance, model-card, and Nebraska
  case-study copy rendered into the static site.
- `site/` retains the historical V1 release. V2 is freshly built from
  `apps/site/` and pinned public artifacts into a sealed release directory.

## Definitions

For a daily mean temperature `tbar` in degrees Fahrenheit, heating degree days
are `max(65 − tbar, 0)` and cooling degree days are `max(tbar − 65, 0)`.
Monthly indexes sum those daily values. County `tbar` is daily TAVG; station
`tbar` is the arithmetic mean of quality-controlled integer-F TMAX and TMIN.
This station calculation reproduces the public index convention, but is not
settlement data.

V2 historical hedge effectiveness compares residual sums of squares on the
same paired seasons and denominator. It reports coverage and unavailable
reasons separately. Current eligibility, station choice, contract window and
model/scenario identity are explicit. The retained V1 labels and their original
rule remain documented in [the V1 pre-registration](docs/preregistration.md).

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

These commands reproduce the retained V1 workflow. The V2 commands,
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
