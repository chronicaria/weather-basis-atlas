# Methodology

## Exposure and proxy

The local exposure is a county area-average calendar-month degree-day index.
Heating degree days are `max(65 − TAVG, 0)`; cooling degree days are
`max(TAVG − 65, 0)`. The station proxy uses the same formulas on the arithmetic
mean of quality-controlled station TMAX and TMIN after integer-F conversion.
Monthly indexes are the sum of their daily values.

The atlas considers the supported heating and cooling contract months. It
evaluates index quality over available history even where an index was not yet
listed, because the question is the geographic quality of the index, not the
historical availability of a tradable contract.

## Held-out hedge measurement

At each season, county and station indexes are expressed as anomalies from a
trailing normal of up to thirty earlier seasons. A county needs fifteen prior
seasons and a station needs ten before its anomaly is eligible. An
expanding-window ordinary least-squares fit relates the county anomaly to a
station anomaly. The next season is held out, so the residual used for hedge
effectiveness has not been used to fit that season's hedge ratio. Training
needs fifteen seasons, except that a station beginning after the county panel's
start may use the pre-registered ten-season short-record rule.

The search compares the geographically nearest station, the best historical
training correlation, and a point-in-time choice. The point-in-time rule ranks
only information available before the realized season, then freezes the station
choice before scoring that season. It requires at least five prior
out-of-sample observations and uses the trailing ten available test seasons.
When no candidate is eligible, the fallback comparison is the contemporaneous
training R-squared for all valid stations. A short-record station has a
separate, pre-registered availability rule; its status is shown rather than
hidden.

Hedge effectiveness is one minus the ratio of hedged residual variation to
comparable unhedged county-anomaly variation. The atlas also retains residual
tail summaries, worst season, test count, and the full station comparison for
each county.

## Uncertainty and maps

Year-block bootstrap resampling holds the point-in-time station sequence fixed
and produces one thousand replicate, ninety-percent uncertainty intervals for
the pooled result. A county is classified as hedgeable only when point-in-time
hedge effectiveness is at least one-half and the lower bound is at least
one-quarter. The map separates effectiveness, selected station, and
exceptions; confidence hatching reflects density and variance diagnostics
rather than in-sample fit.

The headline, map summaries, and README use the same release result. The
underlying county, station, bootstrap, and zero-distance tables are available
in the atlas result directory and are described by their stage manifest.

## Predictive distributions and pricing

The distribution ladder begins with an empirical benchmark, adds a seasonal
parametric model, and then a daily seasonal model with a fitted seasonal mean,
autoregressive residual structure, seasonal variance, and stationary-bootstrap
innovations. Its tournament aggregates proper scoring performance at the
state-month unit, avoiding per-county significance claims. The joint site
stream uses common innovations for county and station series so the pricing
residual retains simulated dependence.

The site labels quote panels as model estimates. A mid is an expected payoff;
the displayed bid and ask indications add transparent residual-risk,
model-uncertainty, and friction conventions. They are not executable prices.

All displayed predictive distributions and quote components come from the same
joint site simulation. The tournament's selected marginal rung is a diagnostic
label, not a license to mix distributional sources within a county panel.

## Data conventions and caveats

County temperatures are a frozen, gridded, homogenized nClimGrid-Daily
vintage. The scaled series necessarily has a limited look-ahead in level and
trend for a historical point-in-time exercise. Station data are frozen
GHCN-Daily snapshots, with documented quality flags, short gap filling, and
provisional-month exclusions. These choices are project conventions where they
are not dictated by the index rulebook.

Further detail, source provenance, and non-claims appear on the about page and
in the model card.
