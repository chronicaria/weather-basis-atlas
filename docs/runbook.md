# Reproduction runbook

This runbook rebuilds Weather Basis Atlas from the committed snapshot and
records the provenance of every stage. Use a clean checkout for a release
reproduction. Do not refresh an upstream source during a frozen reproduction:
GHCN-Daily files may change after retrieval.

## Environment

```bash
uv sync --frozen
uv run wba --help
uv run ruff check .
uv run pytest
```

The application reads defaults from `config/defaults.yaml` and source vintages
from `config/data_vintage.yaml`. A change to either input that affects a
registered default requires a decision record in `docs/decisions/`.

## Frozen inputs

Verify existing input bytes before deriving an artifact:

```bash
uv run wba data verify
```

For a portable reproduction, create or use a raw-data snapshot rather than
making new network requests:

```bash
uv run wba data snapshot export --out wba-raw-snapshot.tar
uv run wba data snapshot import --from wba-raw-snapshot.tar
uv run wba data verify
```

Each fetch and migration is represented by a row under `data/manifests/` with
the retrieval URL, byte count, digest, HTTP metadata when available, and
retrieval time. The donor nClimGrid snapshot is copied, never moved, and is
checked against its donor manifest.

## Build sequence

Run stages in this order. Each stage writes a manifest under
`results/manifests/`; retain it with the resulting files.

```bash
uv run wba data panel --variable tavg
uv run wba data qc
uv run wba contracts check
uv run wba indices build
uv run wba atlas run
uv run wba atlas headline
uv run wba models fit
uv run wba models tournament
uv run wba models simulate
uv run wba quotes run
uv run wba nebraska run
uv run wba site build
uv run wba site check
```

The exact model commands available in a release are discoverable with
`uv run wba models --help`. Never change an analysis window, a seed, or a
release threshold just to make a gate pass; write a decision record first.

## Gates

Run the gates in sequence after their required artifacts exist:

```bash
uv run wba gate 0
uv run wba gate 1
uv run wba gate 2
uv run wba gate 3
uv run wba gate 4
uv run wba gate 5
uv run wba gate 6
uv run wba gate 7
```

The final gate also checks that the rendered release has no unresolved metric
slots, that release artifacts reproduce byte-for-byte where specified, and
that the site payloads and local browser smoke test agree.

## Determinism and release checks

Use the fixture route for a compact command-path check:

```bash
uv run wba reproduce --fixture --out /tmp/weather-basis-atlas-fixture
```

Use the snapshot route for the release-equivalence check. The output directory
must not already exist; it becomes a standalone rebuilt checkout containing
the imported frozen inputs and its own `results/manifests/reproduce.json`.

```bash
uv run wba reproduce --snapshot wba-raw-snapshot.tar --out /tmp/weather-basis-atlas-release
```

Compare the recorded hashes for the headline, atlas pair table, and quote table
in `/tmp/weather-basis-atlas-release/results/manifests/reproduce.json`. Record
the command runtime, maximum county payload size, total site size, gate dates,
decision records, known limitations, and any human-only tasks in `PROGRESS.md`.

## Operating constraints

The workflow is research-only. Do not upload raw data or deploy a release under
an account without confirming the destination and applicable source terms.
The public deployment step remains a human-controlled action because it selects
the hosting identity and makes the artifact externally visible.
