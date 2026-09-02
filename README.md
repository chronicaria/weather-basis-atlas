# Weather Basis Atlas

<!-- atlas-headline:start -->
Weather Basis Atlas finds that 85.1% of counties meet the pre-registered January HDD hedgeability rule and 52.4% meet it for July CDD.
<!-- atlas-headline:end -->

It evaluates calendar-month heating-degree-day and cooling-degree-day indexes
for CONUS counties against the listed U.S. weather-station index universe.
The atlas uses rolling, held-out observations and a point-in-time selection
rule. It is designed to show the geographic limits of a station proxy, not to
recommend a trade.

## What is in this repository

- `data/` contains manifests, metadata, contracts, and reproducible input
  records. Raw source files are deliberately versioned separately from derived
  panels.
- `results/atlas/` contains the county and station-level out-of-sample atlas,
  bootstrap output, zero-distance checks, and the release headline source.
- `results/indices/` contains monthly county and station index panels.
- `results/qc/` records panel, station, geography, and vintage checks.
- `docs/site/` contains the methodological, provenance, model-card, and
  Nebraska case-study copy rendered into the static site.
- `site/` is the locally built static release artifact; its county payloads
  are deterministic gzip files.

## Definitions

For a daily mean temperature `tbar` in degrees Fahrenheit, heating degree days
are `max(65 − tbar, 0)` and cooling degree days are `max(tbar − 65, 0)`.
Monthly indexes sum those daily values. County `tbar` is the county daily TAVG;
station `tbar` is the arithmetic mean of quality-controlled integer-F TMAX and
TMIN observations. This station calculation reproduces the published index
rule, but it is not settlement data.

The primary outcome is held-out hedge effectiveness: one minus the hedged
residual sum of squares divided by the comparable unhedged anomaly sum of
squares. A county is labelled hedgeable only under the jointly pre-registered
point-in-time effectiveness and bootstrap-lower-bound rule. Definitions,
selection, and uncertainty procedures are fixed in
[the pre-registration](docs/preregistration.md).

## Reproduce locally

The workflow uses Python and `uv`:

```bash
uv sync --frozen
uv run wba --help
uv run wba data verify
uv run wba indices build
uv run wba atlas run
uv run wba atlas headline
uv run wba site build
uv run wba site check
```

The complete command sequence, snapshot workflow, deterministic checks, and
release checklist are in [docs/runbook.md](docs/runbook.md). The frozen
protocol is in [docs/preregistration.md](docs/preregistration.md); data
vintages and their source hashes are recorded in `data/manifests/` and
`results/manifests/`.

## Interpretation boundary

Research and education only. Outputs are model estimates, not executable
quotes, offers, insurance, investment advice, or a promise of future hedge
performance. The project is not affiliated with, endorsed by, or sponsored by
CME Group or Speedwell/Xweather. Station names identify public NOAA stations;
no exchange price data are reproduced.

## License and sources

Code is MIT licensed. Data retain their source terms; the source catalogue and
retrieval records belong in `data/contracts/README.md`, `data/manifests/`, and
the site provenance page. See [the about page source](docs/site/about.md) for
the data boundary and known limitations.
