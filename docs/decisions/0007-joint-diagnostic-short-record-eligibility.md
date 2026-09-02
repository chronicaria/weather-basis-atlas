# Decision 0007: apply the registered short-record rule in the joint diagnostic

Date: 2026-09-02

Decision: in the R2j-versus-independent rolling diagnostic only, the Burbank
station becomes evaluable after ten complete prior seasons, and its diagnostic
aggregates the eligible later origins. Every other station and every production
site/tournament model retains the 25-year station-model eligibility rule.

Supersedes: D-61's 25-year station minimum only for the D-47 / Section 7.6.4
18-location diagnostic. It implements D-41's explicit short-record rule and
does not change any selection, hedgeability, or quote threshold.

Reasoning: Section 7.6.4 requires all 13 CME counties plus five Nebraska
counties, while Burbank begins in 1998 and cannot accumulate 25 years before
the final 2022 tournament origin. Applying D-61 without its registered D-41
short-record exception makes the mandated 18 by 14 diagnostic structurally
impossible. Ten prior seasons is the pre-registered station minimum already
used for Burbank in the historical atlas.

Evidence: the rolling diagnostic's pre-result eligibility check found no
D-61-eligible Burbank origin in 1991--2022. The output records `n_origins` and
`short_record` for every row so the shorter comparison cannot be hidden.

Consequences: the diagnostic retains all 252 required location-pair rows and
applies Decision 0004's aggregate-CRPS and exact-sign-test gate. Burbank's
smaller origin count is disclosed; production model availability is unchanged.
