# V2 release and recovery

V2 releases are built from a frozen release lock into a new directory. The
builder never runs a weather model, downloads source data, or substitutes an
unlocked artifact. A template-only change creates a new presentation release
from the same accepted scientific artifacts.

## Published asset

The immutable release is [v2.0.0-20260905](https://github.com/chronicaria/weather-basis-atlas/releases/tag/v2.0.0-20260905),
from merged source `59e8c3702ea56770249301187d004811b8132186`.
Use `weather-basis-atlas-v2-published.tar.gz`:

- Release: `release:306bdf8f6a3a1c31762f00b668d43e26f1cf0a33273dc51baf23f9d7635bef74`
- Bundle: `bundle:500a17e4202c6bc05fad8e2f7daa993cdedc204dc594397a3006c42210d85ae6`
- Archive SHA-256: `3b9588fecc7db5f3a3cfdfa0dabdb05238aba4fbe153ddd31610096de0532f45`

The archive is 704,474,367 bytes and expands to the verified 749,244,937-byte
site with 93,495 files. [Fresh complete extraction](../../results/v2/validation/published-bundle-recovery.json)
passed. The earlier `weather-basis-atlas-v2.tar.gz` and `weather-basis-atlas-v2-prior.tar.gz`
are preserved prepublication candidates, not the deployable final asset.

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
deployment content. These assets are now retained on the immutable release above.

The Pages workflow is manually dispatched with the GitHub Release asset URL,
archive SHA-256, and expected `release_id`. Dispatch it from the release tag
(`gh workflow run pages.yml --ref <tag> …`) so the checkout, dependency lock
and verifier are the ones sealed with that release, including on rollback. It downloads only that asset,
checks the archive digest, extracts exactly one bundle, requires its V1 archive
entrypoint, runs `wba v2 release verify`, compares the embedded ID, and uploads
only that verified directory to Pages. It never uploads the tracked `site/`
directory or fetches mutable weather inputs. Do not dispatch it until the full
candidate lock and its accepted public artifacts exist.

## Presentation-only releases (V2.1 and later)

A change confined to `apps/site/` (templates, styles, scripts) is a new
presentation of the same accepted scientific artifacts. Do not rerun any
scientific stage. Iterate against a sealed bundle without resealing:

```bash
python3 scripts/serve_site.py --bundle build/releases/v2-published --port 8790
```

The dev server serves `apps/site` templates, styles and scripts (resolving the
release placeholder) and takes data, map vendor files and the V1 archive from
the bundle. When the front end is ready, derive a lock that keeps every
scientific pin and recomputes only `presentation.source_hashes`, then build,
verify, package and publish exactly as above:

```bash
uv run python scripts/presentation_lock.py \
  --base config/releases/v2-candidate.lock.json \
  --out config/releases/v2.1-presentation.lock.json
uv run wba v2 release build --lock config/releases/v2.1-presentation.lock.json \
  --out build/releases/v2.1
uv run wba v2 release verify --bundle build/releases/v2.1
uv run python scripts/package_release.py --bundle build/releases/v2.1 \
  --out build/release-assets/weather-basis-atlas-v2.1.tar.gz
```

`presentation_lock.py` copies every scientific pin unchanged (accepted artifacts,
public source, V1 archive, scientific configuration identity, scenario sets, model
specs, data vintages), recomputes the presentation digests, refreshes the Python
source inventory when a module changed, and asserts the scientific identity is
untouched before writing. The site builder additionally refuses to publish a file
under `apps/site` that the lock does not pin, so the release ID identifies every
presentation byte it ships.

The new lock yields a new `release:` identity because the lock content changed;
the public objects inside the bundle are re-stamped with that identity by the
builder, while their scientific `analysis_id`, `scenario_set_id` and source
artifact ids are unchanged. Record the tag, asset SHA-256 and release id in
PROGRESS.md after the Pages workflow succeeds.

## Recovery

`rollback_release(bundle, target)` verifies a prior sealed bundle and copies it
atomically to an explicit fresh local target. `target` must not exist and its
parent must be writable; recovery never overwrites a directory. This is the
retrieval and hash-verification stage of recovery. Uploading that verified
directory and checking the deployed release identity are separate authorized
transport steps.

The final V2 asset is published and Pages run 34001239283 succeeded.
[Exact live byte checks](../../results/v2/validation/public-release-smoke.json)
and [actual public browser journeys](../../results/v2/validation/public-browser-smoke.json)
passed. The V1 archive and tracked `site/` tree are retained explicitly.
