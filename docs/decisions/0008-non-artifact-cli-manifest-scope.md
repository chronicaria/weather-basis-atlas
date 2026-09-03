# Decision 0008: scope stage manifests to artifact-producing CLI runs

Date: 2026-09-03

Decision: every successful CLI command that creates or validates a repository
artifact writes a stage manifest. This includes data acquisition, verification,
snapshot transport, panel construction, contracts validation, gates, fixture
reproduction, and in-repository or fixture site builds/checks. `site serve` and
site builds directed to an external development directory are excluded.

Clarifies: Section 3.4's “every subcommand” rule for the two command modes that
do not create a release artifact owned by the repository.

Reasoning: `site serve` is a long-lived process whose successful return occurs
only when the user stops the server. An external development build is explicitly
outside release provenance and cannot be named in a repository-relative
`paths_out` without weakening the manifest path invariant. Both modes still run
the same site checker before release; neither is used by a numbered gate or by
snapshot reproduction.

Consequences: all release and reproduction paths remain manifested. Temporary
external files and a manually stopped HTTP server do not create misleading
provenance records.
