# Decision 0009: read live release evidence from the manifest extra section

Date: 2026-09-05

Decision: `write_release_manifest` records the selected HTTPS URL and the
validated live-smoke result in the standard stage-manifest `extra` section.
Gate 7 reads both fields from that section, matching the reproduction gate's
existing compatibility pattern.

Clarifies: Section 10, Phase 7's live-release gate and Section 13.3's stage
manifest format.

Reasoning: the release helper already used `write_stage_manifest`, which owns
the common provenance schema and intentionally places stage-specific evidence
under `extra`. Gate 7 incorrectly expected two stage-specific fields at the
top level, making a manifest produced by the helper impossible to pass. The
helper now also rejects a supplied smoke result unless it passed with zero
external requests.

Evidence: the live GitHub Pages site returned HTTP 200 for the home page,
metadata, and default county payload. Browser automation loaded Lancaster
County, changed the layer and pair, moved the strike slider, observed updated
quotes and the no-bid state, recorded only same-origin requests, and reported
no console or page errors.

Consequences: release evidence is generated through the provenance helper
rather than hand-written. Existing manifest consumers retain the standard
schema, and Gate 7 can verify the actual deployed release.
