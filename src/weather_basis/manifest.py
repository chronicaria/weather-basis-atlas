"""Stage provenance manifests and clean-tree enforcement."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Manifest:
    run_id: str
    stage: str
    created_utc: str
    git_commit: str
    config_hash: str
    vintages: dict[str, str]
    geography_vintage: str
    seed: int | None
    paths_in: list[str]
    paths_out: list[str]
    sha256_out: dict[str, str]
    holdout_unlocked: bool
    prereg_sha256: str | None
    extra: dict[str, Any]


def _repo_root() -> Path | None:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
    )
    if completed.returncode:
        return None
    return Path(completed.stdout.strip())


def git_commit(root: Path | None = None) -> str:
    """Return a checkout's current commit, or ``unknown`` outside Git.

    The optional root keeps manifests correct when a pipeline is invoked from
    a wrapper process whose working directory is not the repository itself.
    Snapshot reproduction sets ``WBA_SOURCE_COMMIT`` after checking out that
    exact revision and removing Git metadata from the isolated work directory.
    """

    reproduced_commit = os.environ.get("WBA_SOURCE_COMMIT")
    if reproduced_commit:
        if len(reproduced_commit) != 40 or any(
            character not in "0123456789abcdef" for character in reproduced_commit.lower()
        ):
            raise ValueError("WBA_SOURCE_COMMIT must be a full 40-character Git SHA")
        return reproduced_commit.lower()

    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Keep this module independent of ``io`` per the import boundary."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _changed_tracked_files(root: Path) -> set[Path]:
    names: set[Path] = set()
    for command in (["git", "diff", "--name-only"], ["git", "diff", "--cached", "--name-only"]):
        completed = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
        if completed.returncode == 0:
            names.update(root / name for name in completed.stdout.splitlines() if name)
    return names


def _normalise_path(path: str, root: Path) -> Path:
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def _dirty_before_start(
    m: Manifest, started_at: datetime, *, repo_root: Path | None = None
) -> list[str]:
    root = repo_root.resolve() if repo_root is not None else _repo_root()
    if root is None:
        return []
    allowed = {_normalise_path(name, root) for name in m.paths_out}
    normalized_start = (
        started_at.astimezone(UTC) if started_at.tzinfo else started_at.replace(tzinfo=UTC)
    )
    start_timestamp = normalized_start.timestamp()
    dirty: list[str] = []
    for candidate in _changed_tracked_files(root):
        resolved = candidate.resolve()
        if resolved in allowed:
            continue
        # A tracked deletion is just as material as an edited source file.  It
        # has no mtime to compare, so conservatively treat it as pre-existing
        # dirty state unless it is an output owned by this command.
        if not candidate.exists():
            dirty.append(str(candidate.relative_to(root)))
            continue
        if candidate.stat().st_mtime >= start_timestamp:
            continue
        dirty.append(str(candidate.relative_to(root)))
    return sorted(dirty)


def write_manifest(
    m: Manifest,
    path: Path,
    *,
    started_at: datetime,
    allow_dirty: bool | None = None,
    repo_root: Path | None = None,
) -> None:
    """Write a canonical manifest, enforcing the pre-existing dirty-tree rule.

    ``allow_dirty`` is optional so the stage orchestration can pass the frozen
    ``cfg.allow_dirty`` value.  Metadata is evidence, not authorization: a
    caller cannot bypass the clean-tree rule by writing a value in ``extra``.
    """

    dirty = _dirty_before_start(m, started_at, repo_root=repo_root)
    permitted = False if allow_dirty is None else allow_dirty
    if dirty and not permitted:
        joined = ", ".join(dirty)
        raise RuntimeError(f"refusing to write manifest with pre-existing dirty files: {joined}")
    extra = dict(m.extra)
    if dirty:
        extra["dirty_tree"] = True
        extra["dirty_paths"] = dirty
    manifest = replace(m, extra=extra)
    payload = json.dumps(asdict(manifest), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    _atomic_write_bytes(path, payload.encode("utf-8"))


def read_manifest(path: Path) -> Manifest:
    """Read a manifest written by :func:`write_manifest`."""

    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    return Manifest(**data)
