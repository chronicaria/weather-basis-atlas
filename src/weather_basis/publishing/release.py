"""Fresh, sealed static-release construction for V2.

This module never runs a scientific stage.  It consumes a lock whose source and
accepted-artifact bytes are already pinned, calls the public-site projector,
and atomically publishes a separately verifiable bundle.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml

from weather_basis.provenance.ids import canonical_json, content_id, file_sha256
from weather_basis.schemas.base import require, validate_json

BUNDLE_SCHEMA_VERSION = "2.0"
LOCK_SCHEMA_VERSION = "2.0"
_BUNDLE_MANIFEST = "bundle-manifest.json"
_LOCK_COPY = "release-lock.json"
_REQUIRED_ROUTES = {"/", "/compare", "/contract", "/portfolio", "/research/"}
PAGES_MAX_BYTES = 1_000_000_000
_JINJA_EXPRESSION = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z0-9_.-]*\s*\}\}")
Builder = Callable[..., dict[str, Any]]


def _safe_relative(value: str) -> Path:
    path = Path(value)
    require(
        not path.is_absolute() and ".." not in path.parts and str(path) not in {"", "."},
        "unsafe path",
    )
    return path


def _tree_sha256(path: Path) -> str:
    """Hash a file or directory from its names, byte digests, and byte sizes."""

    candidate = Path(path)
    if candidate.is_file():
        return file_sha256(candidate)
    if not candidate.is_dir():
        raise FileNotFoundError(candidate)
    records = []
    for item in sorted(candidate.rglob("*")):
        if item.is_file():
            records.append(
                {
                    "path": item.relative_to(candidate).as_posix(),
                    "sha256": file_sha256(item),
                    "bytes": item.stat().st_size,
                }
            )
    if not records:
        raise ValueError(f"empty locked directory: {candidate}")
    return content_id(records, prefix="tree").split(":", 1)[1]


def _load_lock(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    require(isinstance(raw, dict), "release lock must be an object")
    allowed = {
        "schema_version",
        "research",
        "presentation",
        "artifacts",
        "public_source",
        "public_data",
        "legacy_bundle",
        "route_map",
    }
    required = {"schema_version", "research", "presentation", "artifacts", "route_map"}
    require(
        required <= set(raw) and set(raw) <= allowed, "release lock has unknown or missing fields"
    )
    require(raw["schema_version"] == LOCK_SCHEMA_VERSION, "unknown release-lock schema")
    require(isinstance(raw["research"], dict), "research lock must be an object")
    require(isinstance(raw["presentation"], dict), "presentation lock must be an object")
    require(isinstance(raw["artifacts"], list) and raw["artifacts"], "release lock needs artifacts")
    public_sources = [name for name in ("public_source", "public_data") if name in raw]
    require(
        len(public_sources) == 1 and isinstance(raw[public_sources[0]], dict),
        "release lock needs one public source",
    )
    require(isinstance(raw["route_map"], dict), "release lock needs a route map")
    require(isinstance(raw.get("legacy_bundle"), dict), "release lock needs a pinned V1 archive")
    require(
        raw["presentation"].get("base_path") == "/weather-basis-atlas/",
        "unexpected Pages base path",
    )
    require(_REQUIRED_ROUTES <= set(raw["route_map"]), "release lock misses required static routes")
    validate_json(raw)
    return raw


def _verify_locked_path(root: Path, record: Mapping[str, Any], *, label: str) -> None:
    require(set(record) == {"path", "sha256"}, f"{label} requires path and sha256")
    relative = _safe_relative(str(record["path"]))
    actual = _tree_sha256(root / relative)
    require(actual == record["sha256"], f"{label} hash mismatch: {relative}")


def _verify_lock_inputs(root: Path, lock: Mapping[str, Any]) -> None:
    for field in ("configuration_hashes", "source_hashes"):
        for raw_path, digest in lock["research"].get(field, {}).items():
            relative = _safe_relative(str(raw_path))
            require(
                _tree_sha256(root / relative) == digest,
                f"research {field} mismatch: {relative}",
            )
    presentation = lock["presentation"]
    source_hashes = presentation.get("source_hashes")
    require(
        isinstance(source_hashes, dict) and source_hashes, "presentation source hashes are required"
    )
    for raw_path, digest in source_hashes.items():
        relative = _safe_relative(str(raw_path))
        require(
            _tree_sha256(root / relative) == digest,
            f"presentation source hash mismatch: {relative}",
        )
    public_name = "public_source" if "public_source" in lock else "public_data"
    _verify_locked_path(root, lock[public_name], label=public_name)
    if "legacy_bundle" in lock:
        _verify_locked_path(root, lock["legacy_bundle"], label="legacy bundle")
    artifact_ids: set[str] = set()
    for record in lock["artifacts"]:
        require(isinstance(record, dict), "artifact lock entry must be an object")
        require(
            set(record) == {"artifact_id", "path", "sha256", "access_class"},
            "artifact lock entry has unknown or missing fields",
        )
        artifact_id = str(record["artifact_id"])
        require(artifact_id not in artifact_ids, "duplicate release artifact ID")
        artifact_ids.add(artifact_id)
        require(
            record["access_class"] == "public_release",
            "restricted artifact cannot enter public bundle",
        )
        _verify_locked_path(
            root, {"path": record["path"], "sha256": record["sha256"]}, label="artifact"
        )


def release_id(lock: Mapping[str, Any]) -> str:
    """Derive the release identity before bundle files embed it."""

    validate_json(dict(lock))
    return content_id(dict(lock), prefix="release")


def _bundle_files(directory: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.name != _BUNDLE_MANIFEST:
            records.append(
                {
                    "path": path.relative_to(directory).as_posix(),
                    "sha256": file_sha256(path),
                    "bytes": path.stat().st_size,
                }
            )
    require(records, "site builder produced no public files")
    require(
        sum(record["bytes"] for record in records) <= PAGES_MAX_BYTES,
        "bundle exceeds the 1 GB GitHub Pages size limit",
    )
    return records


def _validate_routes(directory: Path, route_map: Mapping[str, Any]) -> None:
    for route, target in route_map.items():
        require(isinstance(route, str) and route.startswith("/"), "invalid static route")
        relative = _safe_relative(str(target))
        require((directory / relative).is_file(), f"missing route target: {route} -> {relative}")
    require((directory / "v1" / "index.html").is_file(), "missing preserved V1 archive entrypoint")


def _validate_generated_files(
    directory: Path, expected_release_id: str, route_map: Mapping[str, Any]
) -> None:
    """Validate only V2 rendered routes and data, never archived V1 bytes."""

    for target in route_map.values():
        path = directory / _safe_relative(str(target))
        text = path.read_text(encoding="utf-8")
        require("__WBA_RELEASE_ID__" not in text, f"unresolved release placeholder: {path}")
        require(
            _JINJA_EXPRESSION.search(text) is None,
            f"unresolved template expression: {path}",
        )
    data_root = directory / "data" / "v2"
    for path in data_root.rglob("*.json") if data_root.is_dir() else ():
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid generated JSON: {path}") from exc
            if isinstance(payload, dict) and "release_id" in payload:
                require(payload["release_id"] == expected_release_id, f"mixed release ID: {path}")


def _default_builder(
    *, root: Path, out: Path, release_id: str, lock: dict[str, Any]
) -> dict[str, Any]:
    from .build import build_site

    builder_lock = dict(lock)
    for name in ("public_source", "public_data", "legacy_bundle"):
        if name in builder_lock:
            builder_lock[name] = builder_lock[name]["path"]
    return build_site(root=root, out=out, release_id=release_id, lock=builder_lock)


def build_release(
    root: Path, lock_path: Path, out: Path, *, builder: Builder | None = None
) -> dict[str, Any]:
    """Build, verify, and atomically seal a fresh immutable release directory."""

    root, lock_path, out = Path(root).resolve(), Path(lock_path).resolve(), Path(out).resolve()
    require(not out.exists(), f"immutable release destination already exists: {out}")
    lock = _load_lock(lock_path)
    _verify_lock_inputs(root, lock)
    expected_release_id = release_id(lock)
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".release-", dir=out.parent))
    try:
        result = (builder or _default_builder)(
            root=root, out=staging, release_id=expected_release_id, lock=lock
        )
        require(isinstance(result, dict), "site builder must return a report object")
        (staging / _LOCK_COPY).write_text(canonical_json(lock) + "\n", encoding="utf-8")
        _validate_routes(staging, lock["route_map"])
        _validate_generated_files(staging, expected_release_id, lock["route_map"])
        files = _bundle_files(staging)
        manifest = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "release_id": expected_release_id,
            "release_lock_id": content_id(lock, prefix="release-lock"),
            "route_map": lock["route_map"],
            "files": files,
            "bundle_digest": content_id(files, prefix="bundle"),
        }
        (staging / _BUNDLE_MANIFEST).write_text(canonical_json(manifest) + "\n", encoding="utf-8")
        verify_release(staging)
        os.replace(staging, out)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return inspect_release(out)


def verify_release(bundle: Path) -> dict[str, Any]:
    """Prove a sealed bundle still matches its lock, route map, and byte inventory."""

    directory = Path(bundle)
    manifest_path = directory / _BUNDLE_MANIFEST
    require(manifest_path.is_file(), "missing bundle manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "release_id",
        "release_lock_id",
        "route_map",
        "files",
        "bundle_digest",
    }
    require(set(manifest) == required, "unknown or missing bundle manifest fields")
    require(manifest["schema_version"] == BUNDLE_SCHEMA_VERSION, "unknown bundle schema")
    lock_path = directory / _LOCK_COPY
    require(lock_path.is_file(), "missing embedded release lock")
    lock = _load_lock(lock_path)
    expected_release_id = release_id(lock)
    require(manifest["release_id"] == expected_release_id, "bundle release ID does not match lock")
    require(
        manifest["release_lock_id"] == content_id(lock, prefix="release-lock"),
        "bundle lock ID mismatch",
    )
    require(manifest["route_map"] == lock["route_map"], "bundle routes do not match lock")
    _validate_routes(directory, manifest["route_map"])
    files = manifest["files"]
    require(isinstance(files, list) and files, "bundle file inventory is empty")
    require(
        sum(record.get("bytes", -1) for record in files) + manifest_path.stat().st_size
        <= PAGES_MAX_BYTES,
        "bundle exceeds the 1 GB GitHub Pages size limit",
    )
    require(
        manifest["bundle_digest"] == content_id(files, prefix="bundle"), "bundle digest mismatch"
    )
    seen: set[str] = set()
    for record in files:
        require(set(record) == {"path", "sha256", "bytes"}, "invalid bundle file record")
        relative = _safe_relative(str(record["path"]))
        require(relative.as_posix() not in seen, "duplicate bundle file record")
        seen.add(relative.as_posix())
        path = directory / relative
        require(
            path.is_file() and path.stat().st_size == record["bytes"],
            f"bundle file changed: {relative}",
        )
        require(file_sha256(path) == record["sha256"], f"bundle file hash changed: {relative}")
    actual_paths = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path != manifest_path
    }
    require(actual_paths == seen, "bundle contains unlisted or missing files")
    _validate_generated_files(directory, expected_release_id, manifest["route_map"])
    return manifest


def inspect_release(bundle: Path) -> dict[str, Any]:
    """Return verified release identity, routes, and inventory for an operator."""

    manifest = verify_release(bundle)
    return {
        "release_id": manifest["release_id"],
        "bundle_digest": manifest["bundle_digest"],
        "routes": dict(manifest["route_map"]),
        "file_count": len(manifest["files"]),
        "served_bytes": sum(record["bytes"] for record in manifest["files"])
        + (Path(bundle) / _BUNDLE_MANIFEST).stat().st_size,
        "bundle": str(Path(bundle).resolve()),
    }


def rollback_release(bundle: Path, target: Path) -> dict[str, Any]:
    """Recover a verified prior bundle to an explicit fresh local target.

    Deployment transport and post-deploy URL verification remain a separate,
    authorized operation; this function only performs the recoverable local
    retrieval step needed before that transport.
    """

    inspect_release(bundle)
    source, destination = Path(bundle).resolve(), Path(target).resolve()
    require(not destination.exists(), f"rollback target already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".rollback-", dir=destination.parent))
    try:
        shutil.copytree(source, staging, dirs_exist_ok=True)
        verify_release(staging)
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return inspect_release(destination)
