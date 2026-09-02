# Exclude drifted 2026 auxiliary temperature months

Date: 2026-09-02

Supersedes: D-11 for the usable TMAX/TMIN consistency window only.

Decision: retain the frozen `nclimgrid_tavg` snapshot through 2026-06. Manifest the freshly fetched TMAX and TMIN files through 2026-06, but mark their 2026-01 through 2026-06 panel cells unavailable. The auxiliary consistency window therefore ends 2025-12.

Reasoning: NOAA regenerates scaled months. TMAX/TMIN fetched on 2026-09-02 reconcile with the frozen TAVG snapshot to at most 0.0271°F for 2023-01 through 2025-12, but differ by as much as 6.9210°F in 2026. Combining those vintages would fail the plan's algebraic consistency invariant and silently mix revisions. Replacing the frozen TAVG vintage would violate D-10 and change the pre-registered atlas input.

Evidence: `results/qc/panel_consistency.json` records the accepted common-vintage window and `results/qc/panel_consistency_drift.json` records the excluded 2026 discrepancy.

Consequences: V1's TMAX/TMIN auxiliary diagnostic ends six months before TAVG. County indexes, atlas results, and site valuation remain on the frozen TAVG through 2026-06.
