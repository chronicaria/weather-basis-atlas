# Data, provenance, and interpretation

## Provenance

The county exposure layer is a frozen nClimGrid-Daily county TAVG vintage.
Station inputs are frozen GHCN-Daily snapshots, with station metadata and
change-event records from NOAA's station-history service. County names,
internal-point centroids, and population weights use Census sources. The
contract universe, calendar, and index conventions are kept in
`data/contracts/`; the source manifest catalogue records URLs, retrieval
metadata, and cryptographic digests.

Every released calculation has a stage manifest with its input provenance,
configuration identity, seed, software revision, and output files. Upstream
sources that regenerate are not silently refreshed. The auxiliary-temperature
vintage exclusion is documented in the decision record under `docs/decisions/`.

County geometry and the input panel are reconciled explicitly. The one atlas
geometry without an input county series remains visible as an exception rather
than being imputed. Station-to-county assignments come from the Census
geocoder; the saved assignment table is the authoritative record, including
the recorded county for each station.

## Project conventions

The station index is calculated from daily integer-F maximum and minimum
temperatures. Quality-flagged values are treated as missing. Very short gaps
may be filled by a documented interpolation rule; a materially incomplete
month is excluded. These are project quality-control conventions and are not a
claim about exchange settlement procedures.

The atlas uses historical index quality, not a contemporaneous contract listing
screen. Its selection sequence is point-in-time, but the gridded county layer
has a documented homogenization look-ahead and station archives have a
real-time-to-archive lag. See the model card for the implications and limits.

## Model card

The model card explains intended use, claims and non-claims, data construction,
model selection, pricing conventions, diagnostics, and known limitations. Its
result-dependent diagnostics are read from release artifacts, not inferred
from prose.

## Market context

The contract-universe reference documents the listed U.S. weather stations and
the dated product change reflected in this project. CME material describes
weather contracts as primarily ClearPort block products. Contemporary
third-party and exchange publications cited in the project source catalogue
describe open-interest and volume context, while the dated weather bulletin
record is retained as an observed screen-volume fact. These facts are context
only: this project makes no liquidity, availability, execution, or price claim.

## Disclaimer

Research and education only. Model outputs are not executable quotes, offers,
insurance, investment advice, or a recommendation. The project is not
affiliated with, endorsed by, or sponsored by CME Group or Speedwell/Xweather.
Station names identify public NOAA stations only, and no exchange price data
are reproduced.
