#!/usr/bin/env python3
"""Build deterministic, inventory-backed research assets without uploading them."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import tarfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

from weather_basis.schemas.vintages import VintageLock

GIB = 1024**3
DEFAULT_GROUPS = {
    "stable-panel": ("data/panel",),
    "raw-inputs": ("data/raw",),
    "frozen-source": (
        "data/contracts",
        "data/manifests",
        "data/metadata",
        "config/data_vintage.yaml",
        "config/vintages",
        "config/contracts",
        "results/indices",
    ),
}


@dataclass(frozen=True)
class FileRecord:
    path: Path
    relative: str
    bytes: int
    sha256: str


class HashingWriter:
    def __init__(self, stream) -> None:
        self.stream = stream
        self.digest = hashlib.sha256()

    def write(self, data: bytes) -> int:
        self.digest.update(data)
        return self.stream.write(data)

    def flush(self) -> None:
        self.stream.flush()

    def close(self) -> None:
        self.stream.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _files(root: Path, paths: Iterable[str]) -> list[Path]:
    result: list[Path] = []
    for raw in paths:
        target = (root / raw).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"path escapes repository: {raw}")
        if not target.exists():
            raise FileNotFoundError(target)
        if target.is_file():
            candidates = [target]
        else:
            candidates = sorted(path for path in target.rglob("*") if path.is_file())
        result.extend(path for path in candidates if path.name != ".DS_Store")
    return sorted(set(result), key=lambda path: path.relative_to(root).as_posix())


def _records(root: Path, files: Iterable[Path]) -> list[FileRecord]:
    return [
        FileRecord(path, path.relative_to(root).as_posix(), path.stat().st_size, _sha256(path))
        for path in files
    ]


def _check_vintage(root: Path) -> dict[str, object]:
    """Check the lock and its referenced source manifests before packaging."""
    lock_path = root / "config/vintages/v1-frozen.yaml"
    raw_lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    if not isinstance(raw_lock, dict):
        raise ValueError("vintage lock must be an object")
    lock = VintageLock.from_dict(raw_lock)
    data_vintage = root / "config/data_vintage.yaml"
    actual_vintage = _sha256(data_vintage)
    if actual_vintage != lock.data_vintage_sha256:
        raise ValueError("config/data_vintage.yaml does not match v1-frozen vintage hash")
    manifest_hashes = {
        _sha256(path) for path in (root / "data/manifests").rglob("*") if path.is_file()
    }
    missing = [
        item.artifact_id for item in lock.artifacts if item.sha256 not in manifest_hashes
    ]
    if missing:
        raise ValueError("vintage artifacts lack matching source manifests: " + ", ".join(missing))
    return {
        "vintage_lock": "config/vintages/v1-frozen.yaml",
        "vintage_id": lock.vintage_id,
        "data_vintage_sha256": actual_vintage,
        "matched_source_artifacts": len(lock.artifacts),
    }


def _parts(records: list[FileRecord], limit: int) -> list[list[FileRecord]]:
    """Conservatively split only between files; a single oversized file fails."""
    result: list[list[FileRecord]] = [[]]
    current = 0
    for record in records:
        if record.bytes > limit:
            raise ValueError(f"single file exceeds asset limit: {record.relative}")
        if result[-1] and current + record.bytes > limit:
            result.append([])
            current = 0
        result[-1].append(record)
        current += record.bytes
    return result


def _write_archive(destination: Path, records: list[FileRecord]) -> tuple[str, int]:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    if destination.exists() or temporary.exists():
        raise FileExistsError(f"refusing to overwrite asset: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("wb") as raw:
        hashed = HashingWriter(raw)
        with gzip.GzipFile(fileobj=hashed, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for record in records:
                    info = archive.gettarinfo(str(record.path), arcname=record.relative)
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    with record.path.open("rb") as stream:
                        archive.addfile(info, stream)
    os.replace(temporary, destination)
    return hashed.digest.hexdigest(), destination.stat().st_size


def _write_metadata(destination: Path, payload: dict[str, object]) -> None:
    destination.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def _package_group(
    root: Path, out: Path, name: str, paths: tuple[str, ...], limit: int
) -> list[dict[str, object]]:
    records = _records(root, _files(root, paths))
    # A first archive preserves a single asset when gzip keeps it below GitHub's
    # 2 GiB per-file limit. Oversized output is then replaced by whole-file parts.
    provisional = out / f"{name}.tar.gz"
    digest, size = _write_archive(provisional, records)
    groups = [records]
    if size >= limit:
        provisional.unlink()
        groups = _parts(records, limit)
    else:
        return [_finish_asset(provisional, name, 1, 1, records, digest, size, paths)]
    return [
        _finish_asset(
            out / f"{name}.part{index:02d}.tar.gz",
            name,
            index,
            len(groups),
            part,
            *_write_archive(out / f"{name}.part{index:02d}.tar.gz", part),
            paths,
        )
        for index, part in enumerate(groups, start=1)
    ]


def _finish_asset(destination, group, number, total, records, digest, size, paths):
    if size >= 2 * GIB:
        raise ValueError(f"asset remains at or above 2 GiB after split: {destination.name}")
    checksum = destination.with_suffix(destination.suffix + ".sha256")
    checksum.write_text(f"{digest}  {destination.name}\n", encoding="utf-8")
    manifest = destination.with_suffix(destination.suffix + ".manifest.json")
    payload = {
        "schema_version": "2.0",
        "asset": destination.name,
        "asset_sha256": digest,
        "asset_bytes": size,
        "group": group,
        "part": number,
        "parts": total,
        "source_roots": list(paths),
        "file_count": len(records),
        "uncompressed_bytes": sum(record.bytes for record in records),
        "files": [
            {"path": record.relative, "bytes": record.bytes, "sha256": record.sha256}
            for record in records
        ],
    }
    _write_metadata(manifest, payload)
    return {"asset": destination.name, "sha256": digest, "bytes": size, "manifest": manifest.name}


def _parse_group(value: str) -> tuple[str, tuple[str, ...]]:
    name, separator, raw_paths = value.partition("=")
    paths = tuple(path for path in raw_paths.split(",") if path)
    if not separator or not name or not paths:
        raise argparse.ArgumentTypeError("--group must be NAME=PATH[,PATH...]")
    return name, paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, default=Path("build/release-assets"))
    parser.add_argument("--group", action="append", type=_parse_group, default=[])
    parser.add_argument("--paths", nargs="+", help="Package one named ad-hoc group")
    parser.add_argument("--name", default="research-assets")
    parser.add_argument("--max-asset-gib", type=float, default=2.0)
    args = parser.parse_args()
    if args.paths and args.group:
        parser.error("--paths and --group cannot be combined")
    root = args.root.resolve()
    out = args.out if args.out.is_absolute() else root / args.out
    limit = int(args.max_asset_gib * GIB)
    if limit <= 0 or limit > 2 * GIB:
        parser.error("--max-asset-gib must be greater than zero and at most 2")
    vintage = _check_vintage(root)
    groups = (
        [(args.name, tuple(args.paths))]
        if args.paths
        else (args.group or list(DEFAULT_GROUPS.items()))
    )
    assets = [
        item
        for name, paths in groups
        for item in _package_group(root, out, name, paths, limit)
    ]
    suffix = f".{groups[0][0]}" if len(groups) == 1 and (args.paths or args.group) else ""
    release_manifest = out / f"research-assets{suffix}.manifest.json"
    _write_metadata(
        release_manifest, {"schema_version": "2.0", "vintage": vintage, "assets": assets}
    )
    print(json.dumps({"assets": assets, "manifest": str(release_manifest)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
