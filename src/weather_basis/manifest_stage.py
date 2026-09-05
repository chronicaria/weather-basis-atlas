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
from urllib.parse import urlparse

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


def _input_paths(root: Path, entries: Iterable[Path]) -> list[Path]:
    """Expand consumed files without requiring them to live below *root*."""

    result: list[Path] = []
    for entry in entries:
        path = Path(entry)
        path = path if path.is_absolute() else root / path
        if not path.exists():
            raise FileNotFoundError(f"cannot manifest missing input: {path}")
        if path.is_file():
            result.append(path)
        elif path.is_dir():
            result.extend(item for item in path.rglob("*") if item.is_file())
        else:
            raise ValueError(f"manifest input is not a regular file or directory: {path}")
    return sorted(set(result), key=lambda item: _input_name(root, item))


def input_hashes(root: Path, inputs: Iterable[Path]) -> dict[str, str]:
    """SHA-256 every file consumed by a stage, including external snapshots."""

    return {_input_name(root, path): file_sha256(path) for path in _input_paths(root, inputs)}


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
    consumed = input_hashes(root, paths_in)
    vintages, geography_vintage, prereg_sha256 = provenance_from_config(root, cfg)
    target = manifest_path or root / "results" / "manifests" / f"{stage}.json"
    target = Path(target) if Path(target).is_absolute() else root / target
    target_name = _relative(root, target)
    metadata = dict(extra or {})
    # The escape hatch is a configuration decision, never a per-call flag.
    # This prevents an individual stage from silently bypassing Section 13.3.
    metadata["allow_dirty"] = bool(getattr(cfg, "allow_dirty", False))
    metadata["sha256_in"] = consumed
    # ``paths_out`` is also the ownership allowlist used by the clean-tree
    # rule.  The manifest must own its prior version on a rerun, but including
    # its digest would be recursive.  State that narrow exception explicitly.
    metadata["self_excluded_from_sha256"] = target_name
    manifest = Manifest(
        run_id=f"{stage}-{config_hash(cfg)}",
        stage=stage,
        created_utc=began.astimezone(UTC).isoformat(),
        git_commit=git_commit(root),
        config_hash=config_hash(cfg),
        vintages=vintages,
        geography_vintage=geography_vintage,
        seed=int(_cfg_value(cfg, "seed")),
        paths_in=sorted(consumed),
        paths_out=sorted({*digests, target_name}),
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
    parquet_filenames: Iterable[str] = (),
    source_commit: str | None = None,
    started_at: datetime | None = None,
) -> Path:
    """Record an honest byte-level comparison for a snapshot reproduction.

    ``reference_root`` and ``reproduced_root`` are expected to be the two
    repository roots.  The required files are deliberately named relative to
    their conventional result locations so that missing artefacts fail rather
    than becoming a misleading ``false`` entry.
    """

    root = Path(root).resolve()
    reference_root = Path(reference_root).resolve()
    reproduced_root = Path(reproduced_root).resolve()
    names = tuple(filenames)
    reference_hashes: dict[str, str] = {}
    reproduced_hashes: dict[str, str] = {}
    equality: dict[str, bool] = {}
    reproduced_files: list[Path] = []
    reference_files: list[Path] = []
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
        reference_files.append(expected)
    parquet_equality: dict[str, bool] = {}
    for name in sorted(set(parquet_filenames)):
        relative = Path(name)
        expected, actual = reference_root / relative, reproduced_root / relative
        if not expected.is_file() or not actual.is_file():
            raise FileNotFoundError(f"reproduction comparison missing {relative}")
        parquet_equality[relative.as_posix()] = file_sha256(expected) == file_sha256(actual)
        reference_files.append(expected)
        reproduced_files.append(actual)
    local_outputs = reference_files if root == reference_root else reproduced_files
    if root not in {reference_root, reproduced_root}:
        raise ValueError("reproduction manifest root must be a compared repository")
    manifest = write_stage_manifest(
        root,
        cfg,
        stage="reproduce",
        outputs=local_outputs,
        paths_in=[snapshot, *reference_files, *reproduced_files],
        extra={
            "snapshot": str(Path(snapshot)),
            "reference_hashes": reference_hashes,
            "reproduced_hashes": reproduced_hashes,
            "hash_equality": equality,
            "parquet_hash_equality": parquet_equality,
            "fresh_clone": True,
            "source_commit": source_commit,
        },
        started_at=started_at,
    )
    return manifest


def write_data_qc_manifest(
    root: Path,
    cfg: Any,
    *,
    outputs: Iterable[Path] | None = None,
    inputs: Iterable[Path] | None = None,
    started_at: datetime | None = None,
) -> Path:
    """Record QC reports and all frozen data layers they inspected."""

    root = Path(root)
    return write_stage_manifest(
        root,
        cfg,
        stage="data_qc",
        outputs=outputs or [root / "results/qc"],
        paths_in=inputs
        or [root / "data/panel", root / "data/manifests", root / "data/metadata"],
        started_at=started_at,
    )


def write_models_fit_manifest(
    root: Path,
    cfg: Any,
    *,
    outputs: Iterable[Path] | None = None,
    inputs: Iterable[Path] | None = None,
    started_at: datetime | None = None,
) -> Path:
    """Record fixed-basis daily-model fit artifacts and the panel they consume."""

    root = Path(root)
    return write_stage_manifest(
        root,
        cfg,
        stage="models_fit",
        outputs=outputs or [root / "data/panel/mean_blocks.npz"],
        paths_in=inputs
        or [
            root / "data/panel/tavg_f32.npy",
            root / "data/panel/dates.npy",
            root / "data/panel/fips.npy",
        ],
        started_at=started_at,
    )


def write_sensitivity_manifest(
    root: Path,
    cfg: Any,
    *,
    outputs: Iterable[Path] | None = None,
    inputs: Iterable[Path] | None = None,
    started_at: datetime | None = None,
) -> Path:
    """Record the pre-registered sensitivity tables and their fitted inputs."""

    root = Path(root)
    return write_stage_manifest(
        root,
        cfg,
        stage="sensitivity",
        outputs=outputs or [root / "results/sensitivities"],
        paths_in=inputs
        or [
            root / "results/atlas",
            root / "results/tournament",
            root / "results/quotes",
            root / "data/panel/mean_blocks.npz",
        ],
        started_at=started_at,
    )


def write_release_manifest(
    root: Path,
    cfg: Any,
    *,
    live_url: str,
    live_smoke: Mapping[str, object] | None = None,
    outputs: Iterable[Path] | None = None,
    inputs: Iterable[Path] | None = None,
    started_at: datetime | None = None,
) -> Path:
    """Write the externally-visible release manifest from an actual HTTPS URL.

    Hosting identity is a human choice.  This helper intentionally refuses a
    blank, local, or placeholder URL rather than inventing one to satisfy a
    release gate.
    """

    parsed = urlparse(live_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or host in {"localhost", "example.com"}:
        raise ValueError("release manifest requires a real HTTPS live_url selected by a human")
    root = Path(root)
    smoke = dict(live_smoke or {})
    if smoke and (smoke.get("passed") is not True or smoke.get("external_requests") != 0):
        raise ValueError("release manifest requires a passing local-only live smoke test")
    return write_stage_manifest(
        root,
        cfg,
        stage="release",
        outputs=outputs or [root / "site", root / "README.md"],
        paths_in=inputs
        or [
            root / "results/atlas",
            root / "results/quotes",
            root / "results/tournament",
            root / "results/sensitivities",
        ],
        extra={"live_url": live_url.rstrip("/"), "live_smoke": smoke},
        started_at=started_at,
    )
