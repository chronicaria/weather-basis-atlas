# Decision 0004: rescind the site-era joint-diagnostic shortcut

Date: 2026-09-02

Decision: the earlier aggregate/percentage rule for a single-site-era
diagnostic is rescinded. The production diagnostic uses registered rolling
daily origin fits and retains the original requirement that aligned R2j have
lower CRPS in every one of the 252 location-pair rows.

Supersedes: the prior contents of Decision 0004 only. No D-xx or plan section is
superseded; Section 7.6.4 and D-64 remain authoritative.

Reasoning: the earlier check used one 2025 outcome and a deterministic
permutation of site-as-of station paths. That was not the rolling-origin
independent-R2 comparator in the pre-registration, so its exceptions could not
justify changing the gate. During the corrected implementation, a compact-array
column mapping bug initially produced 35 failures; the original hard condition
correctly exposed it.

Evidence: after fixing that mapping, all origins use origin-specific fits,
hedges and realized anomalies; R2j uses one shared calendar-day block plan and
independent R2 uses separate series plans. R2j wins 252 of 252 rows and lowers
mean CRPS from 24.776 to 11.396. The exact sign-test p-value is retained only as
a diagnostic.

Consequences: the original every-row gate is restored and no observed exception
is hidden or waived. The corrected rolling output and dependence audit fields
replace the invalid site-era artifact.
