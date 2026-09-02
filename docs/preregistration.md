# Weather Basis Atlas pre-registration

Frozen 2026-09-02, before any atlas statistic was computed. This document fixes the V1 protocol described by decisions D-30–D-85 in the build plan.

## Contract and sample

The local exposure is a county area-average calendar-month HDD or CDD index formed from NOAA nClimGrid-Daily TAVG in °F: daily HDD is `max(65 − TAVG, 0)` and daily CDD is `max(TAVG − 65, 0)`, summed after county averaging. The hedge instrument is the corresponding monthly station index formed from quality-controlled GHCN-Daily TMAX and TMIN. Each element is rounded to integer °F before averaging; the station mean is therefore on a 0.5 °F grid. This is a GHCN-Daily replication of the rulebook definition, not Speedwell settlement data.

The 14 pairs are HDD October–April and CDD April–October. A season is labelled by the calendar year of its contract month. Counties are evaluated from 1981 through the last complete season. The atlas evaluates every station index over its available history regardless of `listed_from`; it asks about hedge quality of an index, not historical tradability.

## Anomalies and rolling hedge

At season `s`, a normal is the mean of up to 30 strictly prior seasons. County anomalies require 15 prior seasons and station anomalies require 10. Every origin uses only seasons before `s`. An expanding-window OLS fits `a_county = alpha + h * a_station`; the realized residual at `s` is out of sample. Training requires 15 seasons, or 10 for stations beginning after 1951.

The fixed first-test schedule is 1981 for Atlanta, Boston, Minneapolis, Portland, LaGuardia, Philadelphia, Sacramento, Cincinnati, Las Vegas, Dallas–Fort Worth, and Chicago O'Hare; 1989 for Houston; and 2018 for Burbank. Burbank is always flagged `short_record`.

We report pooled out-of-sample hedge effectiveness, RMSE, upper and lower ES90, worst residual and season, sample counts, and ES95 only where at least 30 seasons exist. HE is `1 − SSR / SST`, with the county anomaly mean computed on the same evaluable test seasons. No ES99 is reported.

Selection rules are nearest station, highest training correlation, and point-in-time best. Point-in-time best requires at least five prior out-of-sample observations and ranks eligible stations by pooled HE over the trailing ten available test seasons. If no station is eligible, all valid stations are ranked by training R²; candidates at one origin are never compared on different statistics. The selected sequence is frozen before evaluating each realized residual.

## Bootstrap and headline

The year-block bootstrap resamples seasons jointly, holds the point-in-time station sequence fixed, uses 1,000 replicates and 90% intervals, and derives pair-specific child seeds from `SeedSequence(20260901)`. Stability is the share of replicates won by the pooled-best eligible station; below 0.60 means no stable proxy. A county is hedgeable only when point-in-time HE is at least 0.50 and its 90% bootstrap lower bound is at least 0.25. Threshold shares at 0.25, 0.50, and 0.75 use HE alone. Thresholds will not be adjusted after observing results.

For every pair, `headline.json` reports county- and population-weighted no-hedge shares, the share whose final-origin point-in-time best differs from nearest, median HE gain among those counties, no-stable-proxy share, threshold shares, the 13-station zero-distance table, effective station count, sample bounds, bootstrap count, seed, config hash, git commit, and run id. HDD January and CDD July are presented first. README and site headline text may only be rendered from that file.

## Distribution tournament

The predictive ladder is R0 empirical burn, R1 trend plus censored Student-t innovation, and R2 daily seasonal-mean plus AR(p), seasonal variance, and stationary-bootstrap innovations. The inference unit is `(state, month)` and skill is one minus the ratio of summed CRPS. Origins 1991–2022 select models; 2023–2025 are locked and opened once only for narrative confirmation. Each higher rung is selected only when skill is positive and a 90% year-block-bootstrap interval excludes zero. No per-county significance claim is made.

R2j shares one calendar-day innovation block plan across all included series. It is assessed as a joint diagnostic rather than a marginal rung. Every distribution and quote displayed by the site comes from the same R2j site run; the selected tournament rung is only a diagnostic label.

Before results are inspected, the fitted R2 null will be used to report the minimum detectable unit-level skill difference at 80% power for 32 origins.

## Pricing and strikes

The site valuation date is 2026-07-01. R2j uses 10,000 paths; tournament runs use 2,000. Marginal streams and pair-level joint streams are deterministically spawned from seed 20260901. The model-free burn set defines standardized strikes `round(mu + z sigma)` for `z = −1.5, −1, −0.5, 0, 0.5, 1, 1.5`, floored at zero, and percentile strikes 50/80/95. Absolute strikes are integers.

Option mid is expected payoff under the empirical R2j draws. The loaded indication uses the joint-draw minimum-variance station futures hedge, 95% residual expected shortfall on each side with weight 0.5, a 200-replicate burn-bootstrap model load, and one tick of friction per absolute hedge contract. `bid_raw = −A(−X)`; displayed bid is floored at zero and explicitly marked `no_bid` when the raw bid is non-positive. These are actuarial model indications, not executable quotes.

Coherence gates cover payoff bounds, monotonicity and convexity of mids, put-call parity, `bid ≤ mid ≤ ask`, non-negative loads, and the two-load identity. A fixed panel of 50 counties is selected deterministically in ascending FIPS order at evenly spaced ranks. Two independent site seeds must agree within four combined Monte Carlo standard errors for mids and four combined bootstrap standard errors for asks. The panel definition is stored with the quote manifest before the second seed is evaluated.

## Claims and non-claims

The atlas estimates historical out-of-sample terminal-payoff hedge performance and climatological synthetic option indications. It does not reproduce CME prices or Speedwell settlement, condition on a live forecast, establish causal effects, offer insurance, or promise future hedge performance. Confidence flags come only from station-density and variance-regime diagnostics, never model fit.
