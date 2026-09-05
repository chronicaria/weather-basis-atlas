#!/usr/bin/env python3
"""Package a previously sealed V2 bundle for a pinned GitHub Release asset."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import tarfile
from pathlib import Path

from weather_basis.provenance.ids import canonical_json
from weather_basis.publishing.release import inspect_release


def _archive(bundle: Path, destination: Path) -> None:
    """Write a deterministic gzip tar with one top-level release directory."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        destination.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed,
    ):
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for path in sorted(bundle.rglob("*")):
                relative = path.relative_to(bundle)
                info = archive.gettarinfo(
                    str(path), arcname=(Path(bundle.name) / relative).as_posix()
                )
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                if path.is_file():
                    with path.open("rb") as stream:
                        archive.addfile(info, stream)
                else:
                    archive.addfile(info)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Output .tar.gz path")
    args = parser.parse_args()
    bundle, output = args.bundle.resolve(), args.out.resolve()
    report = inspect_release(bundle)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite release asset: {output}")
    _archive(bundle, output)
    digest = _sha256(output)
    checksum = output.with_suffix(output.suffix + ".sha256")
    checksum.write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    asset_manifest = output.with_suffix(output.suffix + ".manifest.json")
    asset_manifest.write_text(
        canonical_json(
            {
                "schema_version": "2.0",
                "release_id": report["release_id"],
                "bundle_digest": report["bundle_digest"],
                "asset": output.name,
                "asset_sha256": digest,
                "asset_bytes": output.stat().st_size,
                "checksum": checksum.name,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"asset": str(output), "sha256": digest, **report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
