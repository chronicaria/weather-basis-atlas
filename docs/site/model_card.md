# Model card

## Intended use

Weather Basis Atlas is a historical basis-risk research tool. It compares a
county degree-day exposure with weather-station degree-day indexes under a
rolling, out-of-sample protocol. The accompanying distribution and quote
panels are climatological model indications at a fixed valuation convention.
They are intended to make model assumptions inspectable, not to provide a
market price.

## Primary claims

The atlas estimates historical terminal-payoff hedge performance for the
specified county and station index definitions. It reports a point-in-time
proxy choice, a nearest-station comparison, bootstrap uncertainty, and
diagnostic confidence flags. The predictive workflow reports distributional
diagnostics by state-month unit and retains a shared-innovation joint stream
for the county and station series used in pricing.

The release tables in `results/atlas/`, `results/tournament/`,
`results/models/`, and `results/quotes/` are the authoritative results. The
site and README must render any numerical conclusion from those files and their
stage manifests.

## What it does not claim

This work does not reproduce CME prices, Speedwell settlement values, order
book liquidity, or a live forecast. It does not establish causality, provide
insurance, recommend a hedge, make a per-county statistical-significance claim,
or predict future hedge performance. A station's inclusion in the index
universe is not evidence that a historical contract was tradable on every
evaluated date.

## Data and target construction

County daily temperatures come from a frozen nClimGrid-Daily TAVG vintage.
Station daily temperatures come from frozen GHCN-Daily station snapshots and
are transformed to the public index convention. A station day with an absent
or quality-flagged maximum or minimum is missing. Runs of at most two missing
days may be linearly filled and then rounded to integer Fahrenheit before the
daily mean is formed; a station-month with more than five percent missing days,
or a longer gap, is excluded. This is a project convention, not an exchange
rule.

The county panel is a gridded and homogenized product. Its scaled daily files
are regenerated upstream; therefore a small look-ahead in level and trend is
unavoidable when those fields are used at historical tournament origins. The
point-in-time convention documents this limitation explicitly. Auxiliary TMAX
and TMIN diagnostics are limited to their verified common-vintage window; the
vintage-drift decision record explains the exclusion outside that window.

GHCN-Daily observations can include recent real-time feeds that are later
replaced in the archive. Recent provisional station months are excluded from
test-season scoring. Station coverage differs materially across locations;
the short-record rule is pre-registered and remains visible in payloads and
site labels.

## Method and validation

County and station anomalies use strictly prior seasons. Hedge ratios are fit
only on preceding observations, while the reported residual is held out. The
point-in-time selection sequence is frozen before that residual is assessed.
Bootstrap resampling holds the selection sequence fixed.

The model ladder contains an empirical burn benchmark, a trend-plus-censored
innovation model, and a daily seasonal model. Tournament comparisons aggregate
CRPS at the state-month inference unit, use origin-block uncertainty, and do
not elevate individual county cells to hypothesis tests. The selected marginal
rung is diagnostic only: public distribution and quote payloads come from the
same joint R2j site run.

The daily model estimates a seasonal mean, an autoregressive residual process,
seasonal innovation scale, and resampled standardized innovations. The R2j
site draw couples included county and station series through a common calendar
day innovation-block plan. This preserves the simulated dependence required by
the residual-risk pricing convention; it is assessed through a joint diagnostic
rather than presented as a separate marginal tournament winner.

The release should report its selected-rung table, joint diagnostic,
calibration diagnostics, sensitivity runs, and pre-registered power statement
from the corresponding result files. Missing or failed diagnostics must be
shown as such; they must never be substituted with narrative estimates.

## Pricing boundary

Option mids are expected payoffs under simulated county index draws. Bid and
ask indications include documented residual-risk, model-uncertainty, and
friction components. A displayed no-bid state means the modelled loaded buyer
value is non-positive; it is not a quote refusal by any market participant.
Strike interpolation in the explorer is labelled as interpolation between
precomputed points.

## Known limitations

- The county temperature layer has the homogenization and vintage look-ahead
  described above; it is not a historical real-time operational feed.
- GHCN-Daily has reporting gaps, quality flags, station changes, and archive
  lag. The quality-control rule reduces but cannot erase those issues.
- County exposure is an area-average temperature index, which can differ from
  a policyholder, crop, facility, or settlement location exposure.
- The analysis is historical and climatological. It omits live weather
  forecasts, financing, transaction constraints beyond the stated convention,
  and actual market microstructure.
- The model is evaluated on finite historical samples. Bootstrap intervals and
  diagnostics describe that procedure's sampling variation, not a guarantee.
