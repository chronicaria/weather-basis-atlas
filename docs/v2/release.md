# V2 release and recovery

V2 releases are built from a frozen release lock into a new directory. The
builder never runs a weather model, downloads source data, or substitutes an
unlocked artifact. A template-only change creates a new presentation release
from the same accepted scientific artifacts.

## Release lock

`build_release(root, lock_path, out)` accepts JSON or YAML. Its top-level keys
are exactly `schema_version`, `research`, `presentation`, `artifacts`, one of
`public_source` or `public_data`, `legacy_bundle`, and `route_map`; no other
top-level key is accepted. `schema_version` is `2.0`. Every digest is SHA-256;
a directory digest is the canonical hash of its relative file names, byte
hashes, and byte counts.

```yaml
schema_version: '2.0'
research:                         # object; optional configuration_hashes/source_hashes are verified
  scientific_config_id: config:accepted
presentation:
  base_path: /weather-basis-atlas/
  source_hashes:
    apps/site/templates/index.html: <sha256>
artifacts:
  - artifact_id: artifact:accepted-atlas
    path: results/v2/atlas/accepted
    sha256: <file-or-tree-sha256>
    access_class: public_release
public_source: # exactly one of public_source or public_data
  path: results/v2/public/source.json
  sha256: <sha256>
legacy_bundle:
  path: var/archive/v1/site
  sha256: <file-or-tree-sha256>
route_map:
  '/': index.html
  /compare: compare.html
  /contract: contract.html
  /portfolio: portfolio.html
  /research/: research/index.html
```

`presentation.base_path` must be `/weather-basis-atlas/`, and its nonempty
`source_hashes` are verified. Each artifact entry has exactly `artifact_id`,
`path`, `sha256`, and `access_class`, and only `public_release` is admitted.
The public and legacy records each have exactly `path` and `sha256`. The lock
itself determines `release_id` before rendering; the final bundle digest is
calculated after rendering and does not participate in that ID.

## Build and verify

The default site projector is `weather_basis.publishing.build.build_site` with:

```python
build_site(*, root: Path, out: Path, release_id: str, lock: dict) -> dict
```

It writes to a fresh staging directory. `build_release` refuses an existing
`out`, verifies all locked inputs, copies the canonical lock into
`release-lock.json`, checks static routes, unresolved HTML template markers,
JSON release IDs, and every byte in the final inventory. It then atomically
renames the sealed directory into `out`; `bundle-manifest.json` records the
complete sealed inventory.

`verify_release(bundle)` rejects a changed file, missing route, wrong release
ID, altered lock, mixed JSON release ID, or unknown bundle schema.
`inspect_release(bundle)` returns the verified release ID, digest, route map,
and file count. A release lock must include a pinned `legacy_bundle`, and every
sealed bundle must contain `v1/index.html`. The verifier also rejects bundles
over GitHub Pages' 1 GB published-site limit.

The GitHub Pages base path is fixed at `/weather-basis-atlas/`. Required static
entry routes are `/` (`index.html`), `/compare` (`compare.html`), `/contract`
(`contract.html`), `/portfolio` (`portfolio.html`), and `/research/`
(`research/index.html`).
Nested research pages must use paths that work after a direct refresh; Pages
does not supply a server-side SPA fallback.

`public_source` is a pinned projection-source JSON document (`bootstrap` plus
objects) whose envelopes may carry a candidate release ID; the site builder
stamps the precomputed ID during projection. `public_data` is the alternative
for an already assembled pinned public-data directory, which must already carry
the precomputed release ID. Both are represented by `{path, sha256}` in the
outer release lock; the builder receives only the validated relative path.
`legacy_bundle` uses the same locked `{path, sha256}` form and
creates the explicit V1 archive route.

## GitHub Release asset and Pages transport

Do not use Actions artifacts as release provenance: their retention is finite.
After a candidate is accepted, build and inspect a fresh sealed directory, then
package that directory as a deterministic GitHub Release asset:

```bash
uv run wba v2 release build --lock config/releases/v2-candidate.lock.json \
  --out build/releases/v2-candidate
uv run wba v2 release verify --bundle build/releases/v2-candidate
uv run python scripts/package_release.py --bundle build/releases/v2-candidate \
  --out build/release-assets/weather-basis-atlas-v2.tar.gz
```

The packager writes three bundle files: the `.tar.gz`, its `.sha256`, and its
`.manifest.json`. The manifest repeats the sealed `release_id`, final bundle
digest, archive byte size, and archive SHA-256. Separately retain the frozen
research-input assets produced by
[`scripts/package_research_assets.py`](../../scripts/package_research_assets.py)
with their inventories and checksums; they are recovery inputs, not Pages
deployment content. No asset has been uploaded or published yet.

The Pages workflow is manually dispatched with the GitHub Release asset URL,
archive SHA-256, and expected `release_id`. It downloads only that asset,
checks the archive digest, extracts exactly one bundle, requires its V1 archive
entrypoint, runs `wba v2 release verify`, compares the embedded ID, and uploads
only that verified directory to Pages. It never uploads the tracked `site/`
directory or fetches mutable weather inputs. Do not dispatch it until the full
candidate lock and its accepted public artifacts exist.

## Recovery

`rollback_release(bundle, target)` verifies a prior sealed bundle and copies it
atomically to an explicit fresh local target. `target` must not exist and its
parent must be writable; recovery never overwrites a directory. This is the
retrieval and hash-verification stage of recovery. Uploading that verified
directory and checking the deployed release identity are separate authorized
transport steps.

V2 candidate validation is underway. V1 remains the current public release
until a V2 bundle, archive routes, authorized upload, and recovery through the
real deployment transport have all been verified. Do not delete the tracked
`site/` tree as part of release-mechanism work.
