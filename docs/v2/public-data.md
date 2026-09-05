# Public V2 data

The public release is a projection of pinned V2 artifacts.  It never refits a
model, selects a station, or simulates weather during site assembly.

`cases.build` writes a small `public-source.json` blueprint and one retained
JSON record per public object.  A release builder materializes those records as
individually gzip-compressed envelopes, hashing the compressed bytes in the
bootstrap lookup.  This keeps a national county/pair catalogue streamable and
avoids constructing a multi-gigabyte JSON matrix in memory.

Production county records come from the corrected R01 output and preserve the
historical evaluation separately from the current as-of station selection.
Physical quotes require finite, exact-ID aligned county and station paths from
the frozen common scenario artifact.  Market observations are always a
separate component and are explicitly unavailable when no observation is
pinned.

The bootstrap includes the 3,107-county registry, all scenario-set identity
fields, the current valuation date, January 2027 defaults, and browser limits:
six locations, 24 exposure rows, 39 hedge columns, 12 months, and 2,000 public
paths.  Book projections compile all three supplied books against the same
common scenario matrix.  Partial or negative research stays labelled as such.
