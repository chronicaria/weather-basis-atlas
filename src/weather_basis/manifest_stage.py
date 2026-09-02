"""Stage-level provenance construction.

This module is deliberately separate from :mod:`weather_basis.manifest`: the
latter owns the on-disk format and clean-tree rule, while this module knows
how a pipeline stage derives that format from the frozen project config and
real files.  Keeping the split makes it difficult for a caller to accidentally
write a partial, hand-filled manifest.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from weather_basis.config import config_hash
from weather_basis.io import sha256 as file_sha256
from weather_basis.manifest import Manifest, git_commit, write_manifest


def _relative(root: Path, path: Path) -> str:
    """Return a repository-relative POSIX path, rejecting paths outside it."""

    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"manifest path is outside repository root: {path}") from exc


def _input_name(root: Path, path: Path) -> str:
    """Use a stable relative name where possible, otherwise retain an absolute input."""

    candidate = path.resolve()
    try:
        return candidate.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(candidate)


def _paths(root: Path, entries: Iterable[Path]) -> list[Path]:
    """Expand declared output files/directories in deterministic order."""

    result: list[Path] = []
    for entry in entries:
        path = Path(entry)
        path = path if path.is_absolute() else root / path
        if not path.exists():
            raise FileNotFoundError(f"cannot manifest missing output: {path}")
        if path.is_file():
            result.append(path)
        elif path.is_dir():
            result.extend(item for item in path.rglob("*") if item.is_file())
        else:
            raise ValueError(f"manifest output is not a regular file or directory: {path}")
    # A stage may name a file directly and through a containing directory.
    return sorted(set(result), key=lambda item: _relative(root, item))


def output_hashes(root: Path, outputs: Iterable[Path]) -> dict[str, str]:
    """SHA-256 every declared stage output, recursively for directories."""

    return {_relative(root, path): file_sha256(path) for path in _paths(root, outputs)}


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    # FrozenDict deliberately implements Mapping, but this keeps diagnostics
    # useful for lightweight configs supplied by tests or a caller.
    raise TypeError("stage manifest requires a mapping-shaped configuration section")


def _cfg_value(cfg: Any, key: str) -> Any:
    try:
        return getattr(cfg, key)
    except AttributeError as exc:
        raise ValueError(f"stage manifest requires config.{key}") from exc


def provenance_from_config(root: Path, cfg: Any) -> tuple[dict[str, str], str, str]:
    """Read data vintages and verify the preregistration hash against disk."""

    vintages = {
        str(key): str(value) for key, value in _mapping(_cfg_value(cfg, "vintages")).items()
    }
    geography_vintage = vintages.get("geography")
    if not geography_vintage:
        raise ValueError("config.vintages.geography is required for every stage manifest")
    preregistration = root / "docs" / "preregistration.md"
    if not preregistration.is_file():
        raise FileNotFoundError(f"missing preregistration: {preregistration}")
    prereg_sha256 = sha256(preregistration.read_bytes()).hexdigest()
    configured = _mapping(_cfg_value(cfg, "prereg")).get("sha256")
    if configured and str(configured) != prereg_sha256:
        raise ValueError("config.prereg.sha256 does not match docs/preregistration.md")
    return vintages, geography_vintage, prereg_sha256


def write_stage_manifest(
    root: Path,
    cfg: Any,
    *,
    stage: str,
    outputs: Iterable[Path],
    paths_in: Iterable[Path] = (),
    holdout_unlocked: bool = False,
    extra: Mapping[str, Any] | None = None,
    started_at: datetime | None = None,
    manifest_path: Path | None = None,
) -> Path:
    """Build and write a complete stage manifest from real filesystem state.

    The file hashes are calculated immediately before the manifest is written;
    callers cannot supply them.  ``started_at`` should be captured before a
    command writes its outputs so the Section 13.3 clean-tree check has the
    correct boundary.
    """

    root = Path(root).resolve()
    began = started_at or datetime.now(UTC)
    digests = output_hashes(root, outputs)
    input_paths = sorted(
        {
            _input_name(root, Path(path) if Path(path).is_absolute() else root / path)
            for path in paths_in
        }
    )
    vintages, geography_vintage, prereg_sha256 = provenance_from_config(root, cfg)
    target = manifest_path or root / "results" / "manifests" / f"{stage}.json"
    target = Path(target) if Path(target).is_absolute() else root / target
    metadata = dict(extra or {})
    # The escape hatch is a configuration decision, never a per-call flag.
    # This prevents an individual stage from silently bypassing Section 13.3.
    metadata["allow_dirty"] = bool(getattr(cfg, "allow_dirty", False))
    manifest = Manifest(
        run_id=f"{stage}-{config_hash(cfg)}",
        stage=stage,
        created_utc=began.astimezone(UTC).isoformat(),
        git_commit=git_commit(root),
        config_hash=config_hash(cfg),
        vintages=vintages,
        geography_vintage=geography_vintage,
        seed=int(_cfg_value(cfg, "seed")),
        paths_in=input_paths,
        paths_out=sorted(digests),
        sha256_out=digests,
        holdout_unlocked=holdout_unlocked,
        prereg_sha256=prereg_sha256,
        extra=metadata,
    )
    write_manifest(
        manifest,
        target,
        started_at=began,
        allow_dirty=bool(metadata["allow_dirty"]),
        repo_root=root,
    )
    return target


def write_reproduction_manifest(
    root: Path,
    cfg: Any,
    *,
    reference_root: Path,
    reproduced_root: Path,
    snapshot: Path,
    filenames: Iterable[str] = ("headline.json", "pairs.parquet", "quotes.parquet"),
    started_at: datetime | None = None,
) -> Path:
    """Record an honest byte-level comparison for a snapshot reproduction.

    ``reference_root`` and ``reproduced_root`` are expected to be the two
    repository roots.  The required files are deliberately named relative to
    their conventional result locations so that missing artefacts fail rather
    than becoming a misleading ``false`` entry.
    """

    reference_root, reproduced_root = Path(reference_root), Path(reproduced_root)
    names = tuple(filenames)
    reference_hashes: dict[str, str] = {}
    reproduced_hashes: dict[str, str] = {}
    equality: dict[str, bool] = {}
    reproduced_files: list[Path] = []
    for name in names:
        if name == "headline.json":
            relative = Path("results/atlas") / name
        elif name == "pairs.parquet":
            relative = Path("results/atlas") / name
        elif name == "quotes.parquet":
            relative = Path("results/quotes") / name
        else:
            relative = Path(name)
        expected, actual = reference_root / relative, reproduced_root / relative
        if not expected.is_file() or not actual.is_file():
            raise FileNotFoundError(f"reproduction comparison missing {relative}")
        reference_hashes[name] = file_sha256(expected)
        reproduced_hashes[name] = file_sha256(actual)
        equality[name] = reference_hashes[name] == reproduced_hashes[name]
        reproduced_files.append(actual)
    manifest = write_stage_manifest(
        root,
        cfg,
        stage="reproduce",
        outputs=reproduced_files,
        paths_in=[snapshot],
        extra={
            "snapshot": str(Path(snapshot)),
            "reference_hashes": reference_hashes,
            "reproduced_hashes": reproduced_hashes,
            "hash_equality": equality,
        },
        started_at=started_at,
    )
    return manifest
