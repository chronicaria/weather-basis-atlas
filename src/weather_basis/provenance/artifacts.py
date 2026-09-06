"""Atomic content-addressed shard publication and validation."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .ids import canonical_json, content_id, file_sha256

MANIFEST_NAME = "artifact-manifest.json"
MANIFEST_SCHEMA_VERSION = "2.0"


@dataclass(frozen=True)
class ArtifactFile:
    path: str
    sha256: str
    bytes: int


@dataclass(frozen=True)
class ArtifactManifest:
    schema_version: str
    artifact_id: str
    stage_id: str
    analysis_id: str
    execution_id: str
    producer_fingerprint: str
    seed_schema_version: str
    status: str
    files: tuple[ArtifactFile, ...]
    inputs: Mapping[str, str]
    created_utc: str
    telemetry: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_relative(path: Path, directory: Path) -> str:
    try:
        return path.relative_to(directory).as_posix()
    except ValueError as exc:
        raise ValueError(f"artifact output escapes staging directory: {path}") from exc


def artifact_files(
    directory: Path, paths: Iterable[Path] | None = None
) -> tuple[ArtifactFile, ...]:
    """Hash regular files in a staging directory, excluding the manifest itself."""

    root = Path(directory)
    candidates = (
        list(paths)
        if paths is not None
        else [path for path in root.rglob("*") if path.is_file()]
    )
    records: list[ArtifactFile] = []
    for candidate in candidates:
        path = Path(candidate)
        if not path.is_absolute():
            path = root / path
        if not path.is_file():
            raise FileNotFoundError(f"declared artifact output is not a file: {path}")
        relative = _safe_relative(path, root)
        if relative == MANIFEST_NAME:
            continue
        records.append(ArtifactFile(relative, file_sha256(path), path.stat().st_size))
    if not records:
        raise ValueError("a completed artifact must contain at least one output file")
    return tuple(sorted(records, key=lambda item: item.path))


def make_manifest(
    directory: Path,
    *,
    stage_id: str,
    analysis_id: str,
    execution_id: str,
    producer_fingerprint: str,
    seed_schema_version: str = "v2-seed-1",
    inputs: Mapping[str, str] | None = None,
    telemetry: Mapping[str, Any] | None = None,
    paths: Iterable[Path] | None = None,
) -> ArtifactManifest:
    """Construct a completion manifest from bytes actually in *directory*."""

    records = artifact_files(directory, paths)
    identity = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "stage_id": stage_id,
        "analysis_id": analysis_id,
        "producer_fingerprint": producer_fingerprint,
        "seed_schema_version": seed_schema_version,
        "inputs": dict(sorted((inputs or {}).items())),
        "files": [asdict(record) for record in records],
    }
    return ArtifactManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        artifact_id=content_id(identity),
        stage_id=stage_id,
        analysis_id=analysis_id,
        execution_id=execution_id,
        producer_fingerprint=producer_fingerprint,
        seed_schema_version=seed_schema_version,
        status="complete",
        files=records,
        inputs=dict(sorted((inputs or {}).items())),
        created_utc=datetime.now(UTC).isoformat(),
        telemetry=dict(telemetry or {}),
    )


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(canonical_json(value))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_manifest(directory: Path, manifest: ArtifactManifest) -> Path:
    """Write completion evidence last, after validating all declared outputs."""

    root = Path(directory)
    validate_manifest(root, manifest, require_manifest=False)
    target = root / MANIFEST_NAME
    _atomic_json(target, manifest.as_dict())
    return target


def read_manifest(directory: Path) -> ArtifactManifest:
    import json

    with (Path(directory) / MANIFEST_NAME).open(encoding="utf-8") as stream:
        raw = json.load(stream)
    raw["files"] = tuple(ArtifactFile(**record) for record in raw["files"])
    return ArtifactManifest(**raw)


def validate_manifest(
    directory: Path, manifest: ArtifactManifest | None = None, *, require_manifest: bool = True
) -> ArtifactManifest:
    """Reject incomplete, schema-incompatible or byte-corrupt published artifacts."""

    root = Path(directory)
    if manifest is None:
        if not (root / MANIFEST_NAME).is_file():
            if require_manifest:
                raise FileNotFoundError(f"missing completion manifest: {root / MANIFEST_NAME}")
            raise ValueError("manifest must be supplied when completion file is absent")
        manifest = read_manifest(root)
    if manifest.schema_version != MANIFEST_SCHEMA_VERSION or manifest.status != "complete":
        raise ValueError("artifact manifest is not a complete V2.0 artifact")
    if not manifest.stage_id or not manifest.analysis_id or not manifest.execution_id:
        raise ValueError("artifact manifest lacks required identity fields")
    expected_identity = {
        "schema_version": manifest.schema_version,
        "stage_id": manifest.stage_id,
        "analysis_id": manifest.analysis_id,
        "producer_fingerprint": manifest.producer_fingerprint,
        "seed_schema_version": manifest.seed_schema_version,
        "inputs": dict(sorted(manifest.inputs.items())),
        "files": [asdict(record) for record in manifest.files],
    }
    if manifest.artifact_id != content_id(expected_identity):
        raise ValueError("artifact manifest content ID does not match its declared content")
    for record in manifest.files:
        candidate = root / record.path
        if Path(record.path).is_absolute() or ".." in Path(record.path).parts:
            raise ValueError(f"unsafe artifact path: {record.path}")
        if not candidate.is_file() or candidate.stat().st_size != record.bytes:
            raise ValueError(f"artifact output missing or size changed: {record.path}")
        if file_sha256(candidate) != record.sha256:
            raise ValueError(f"artifact output hash changed: {record.path}")
    return manifest


def quarantine(directory: Path, quarantine_root: Path, reason: str) -> Path:
    """Move an invalid artifact aside without deleting its forensic evidence."""

    source = Path(directory)
    target_root = Path(quarantine_root)
    target_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = target_root / f"{source.name}-{stamp}"
    os.replace(source, target)
    _atomic_json(
        target / "quarantine.json",
        {"reason": reason, "quarantined_utc": datetime.now(UTC).isoformat()},
    )
    return target


def publish_directory(
    staging: Path, destination: Path, manifest: ArtifactManifest
) -> ArtifactManifest:
    """Publish a validated staging directory atomically; manifests are written last."""

    staging, destination = Path(staging), Path(destination)
    write_manifest(staging, manifest)
    validate_manifest(staging)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"immutable artifact destination already exists: {destination}")
    os.replace(staging, destination)
    return validate_manifest(destination)


def new_staging_directory(parent: Path, label: str) -> Path:
    """Create a unique same-filesystem staging directory for atomic publish."""

    Path(parent).mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f".{label}.", dir=parent))
