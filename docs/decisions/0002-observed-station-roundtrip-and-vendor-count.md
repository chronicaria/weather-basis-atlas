# Decision 0002: preserve observed station round-trip flags and count vendored files

Date: 2026-09-02

The frozen GHCN vintage contains a small but non-zero share of temperature
elements more than 0.10 °F from the nearest integer Fahrenheit value. The
share varies by station and reaches roughly seven percent for this vintage.
These elements remain usable after the registered integer-F conversion, and
their observed flag rate is reported rather than replaced with the plan's
pre-data expectation of less than 0.1 percent. The gate requires each station's
reported rate to remain below ten percent and the raw QC counts remain public.

The four vendored libraries resolve to five files because KaTeX requires both
its JavaScript and stylesheet. `VENDOR.json` therefore verifies five file
hashes. This supersedes the Phase 0 prose that called the file count four; it
does not add a runtime dependency.
