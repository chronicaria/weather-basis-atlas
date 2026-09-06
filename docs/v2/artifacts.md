# V2 artifact catalogue and retention

| Class | Locator | Immutable evidence | Retention and access |
| --- | --- | --- | --- |
| Frozen source vintage | `config/vintages/v1-frozen.yaml` and `data/manifests/` | Source manifest and panel hashes, coverage, QC/imputation rules | Preserve indefinitely; public frozen inputs only |
| Contract support | `config/contracts/v2-temperature.yaml` and `data/contracts/` | Retained document/table hashes and evidence tier | Preserve indefinitely; does not establish listings or market prices |
| Scientific stage artifact | `results/v2/` with artifact manifest | Artifact ID, producer fingerprint, input IDs, output byte hashes | Immutable after acceptance; public projection only if classified for release |
| Public projection source | accepted V2 public-source artifact | Result envelope IDs, source artifact IDs, schema/release compatibility | Retain with its research lock; no restricted source content |
| Sealed release bundle | `build/releases/<release-id>/` or retained release store | `release-lock.json`, `bundle-manifest.json`, bundle digest, route map | Immutable and recoverable; retain the immediately prior verified bundle at minimum |
| Local intermediates | `var/` and unaccepted cache/shards | Stage-local diagnostics only | Ignored and regenerable; never a release dependency unless promoted to an artifact |
| V1 archive | existing tracked `site/` and historical release evidence | V1 provenance and dated documentation | Preserve until archive/route migration and rollback are proven |

Only artifacts whose release-lock entry has `access_class: public_release` may
enter a public bundle. Historical market observations, licensed settlement data,
or local imported holdings are not public-release artifacts by default.

A release lock is the recovery locator: it names the accepted scientific,
vintage, model, scenario, experiment, public-source, and presentation inputs by
content hash. The release manifest proves exactly which rendered files resulted.
Execution timestamps and telemetry belong in separate stage envelopes and do
not change scientific or release identity.

## Hosting and retention decision

GitHub Actions artifacts are transient transport, not the immutable research or
release store: their default retention is 90 days and repository/organization
policy can shorten it. GitHub Pages also limits a published site to 1 GB and a
deployment to 10 minutes. Keep only the small verified public bundle in the
Pages deployment path. Retain accepted scientific inputs and prior sealed
bundles at stable local/release locators recorded in their locks before adding a
workflow that retrieves them. The relevant primary limits are [GitHub Pages
limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
and [Actions artifact retention](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository).

## Frozen research release assets

`scripts/package_research_assets.py` prepares upload-ready assets locally; it
does not create a release or upload anything. Its default groups are
`stable-panel` (`data/panel`), `raw-inputs` (`data/raw`), and `frozen-source`
(`data/contracts`, manifests, metadata, V2 vintage/contract config, and
`results/indices`). The source roots contain only the retained public NOAA and
contract-transcription vintage inputs; private holdings and files outside the
repository are rejected.

```bash
uv run python scripts/package_research_assets.py --root . --out build/release-assets
```

Before packing, the script checks `config/data_vintage.yaml` against the frozen
vintage hash and confirms every locked source artifact has a matching retained
source-manifest digest. Each `.tar.gz` has repository-relative member names,
normalized mtime/ownership, a streaming SHA-256 sidecar, and a byte inventory
manifest. `.DS_Store` is the only excluded filename. Assets at or above the
2 GiB GitHub Release file limit are replaced by whole-file parts; no member is
silently omitted or split.

For an explicit reusable subset, use either:

```bash
uv run python scripts/package_research_assets.py --paths results/indices data/manifests --name index-support
uv run python scripts/package_research_assets.py --group evidence=results/v2/validation,config/vintages
```

Keep the generated `research-assets.manifest.json`, each asset manifest, and
its checksum with the eventual release lock. Extract an asset into an empty
recovery directory with `tar -xzf asset.tar.gz -C recovery`; member paths
recreate their repository-relative locations.

The canonical selected 10,000-path scenario shard is separately retained as
`build/release-assets/national-scenarios-10000.tar.gz`, with its checksum and
inventory beside it. Its source root is
`var/shards/v2/scenarios.build/sha256-750b533a8f349990e6b01b1bb9853e32a163c111291a468417ea8d17f63cf609`;
the archive preserves that exact locator for clean extraction and resume.

## Lifecycle used by the final candidate

The planner first freezes stage coordinates and input hashes; the executor then
either reuses a complete matching shard or writes a fresh staging directory,
validates hashes and schema, and publishes its manifest last. A failed or
corrupt candidate goes to quarantine and cannot become a downstream input.
`cases.build` projects accepted research and public records; `site.build`
turns that identified source into a sealed bundle; `release.verify` checks the
bundle before any hosting action.

The final candidate's downstream run is
[`var/runs/v2-final-research-run.json`](../../var/runs/v2-final-research-run.json).
The B26 next-station report is
[`results/v2/next-station/sha256-a6e569904e030545f18e1e490d64febd2657d45ed0e99af8e9192c7c8d1b9ddf/next_station_report.json`](../../results/v2/next-station/sha256-a6e569904e030545f18e1e490d64febd2657d45ed0e99af8e9192c7c8d1b9ddf/next_station_report.json).
These locators are local evidence inputs, not a declaration that a final site
bundle or public tag has been published.

The release asset packer is preparing the final deltas for the intended
`v2.0.0-20260905` tag. Eight core assets have already been uploaded by the
release owner. Keep the resulting asset checksums and inventory with the final
release lock; do not infer publication from an upload in progress.
