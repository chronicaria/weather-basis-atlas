# Decision 0003: report zero HE for a finite constant target

Date: 2026-09-02

A small number of high-elevation CDD county-month histories contain finite
test observations but effectively zero target variance. The ratio definition
of hedge effectiveness is undefined in that case and floating-point noise can
produce enormous negative values and unusable bootstrap intervals.

For a finite test sample whose centered target sum of squares is at or below
`max(machine epsilon, 1e-12 * max(sum(a^2), 1))`, the atlas now reports hedge
effectiveness of zero, except that an exactly zero residual remains a perfect
hedge with effectiveness one. Missing samples remain missing. This preserves the
fixed 3,107-county universe, makes the convention conservative, and applies
identically to point estimates and bootstrap replicates.
