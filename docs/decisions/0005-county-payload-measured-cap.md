# Decision 0005: set the county payload cap from the Phase 4 measurement

Date: 2026-09-02

Decision: set `site.county_payload_max_kb_gz` to 62 KiB while retaining 1,000
shipped draws, all 14 contract records, all 13 hedge rows, quote grids, and the
complete realized OOS table. Tighten the total-site cap from 300 MB to the
Section 9.2 target of 200 MB.

Supersedes: D-81 and Section 9.2's initial 60 KiB county-payload target only.

Reasoning: the plan explicitly requires the Phase 4 measured maximum to set a
new gate if the complete payload exceeds the target. Removing registered fields
or reducing the draw count would weaken the product more than a measured
1.7-percent cap adjustment.

Evidence: the first complete production payload build contained 3,107 county
files, occupied 195,045,460 bytes in total, and had a maximum compressed county
file of 62,457 bytes (60.99 KiB), with deterministic gzip level 9 and mtime 0.

Consequences: the per-county gate is 62 KiB and the site must remain at or below
200 MB. No statistical threshold, draw count, or payload field changes.

