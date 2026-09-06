"""Bounded atomic shard executor with read-only planning inspection."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from weather_basis.provenance.artifacts import (
    ArtifactManifest,
    make_manifest,
    new_staging_directory,
    publish_directory,
    quarantine,
    validate_manifest,
)

from .planner import PlannedShard
from .telemetry import Telemetry


def _context_handler(handler, context, out_directory: Path, telemetry: Telemetry):
    context.telemetry = telemetry
    return handler(context, out_directory)


def _process_request(root: Path, scratch_dir: Path, request):
    shard, handler, context, inputs, execution_id, resume = request
    executor = ShardExecutor(
        root, ResourceBudget(workers=1, memory_gib=12), scratch_dir=scratch_dir
    )
    return executor.execute(
        shard,
        lambda out, telemetry: _context_handler(handler, context, out, telemetry),
        inputs=inputs,
        execution_id=execution_id,
        resume=resume,
    )


@dataclass(frozen=True)
class ResourceBudget:
    workers: int = 1
    memory_gib: float = 12.0

    def __post_init__(self) -> None:
        if self.workers not in (1, 2):
            raise ValueError(
                "B09 permits only one or two workers pending measured scaling evidence"
            )
        if not 0 < self.memory_gib <= 12:
            raise ValueError("B08 memory reservation must be greater than zero and at most 12 GiB")
        if self.memory_gib < self.workers * 4:
            raise ValueError("worker reservation requires 4 GiB measured RSS headroom per worker")


@dataclass(frozen=True)
class ShardResult:
    shard_id: str
    status: str
    directory: Path
    manifest: ArtifactManifest | None
    quarantine_directory: Path | None = None


class ShardExecutor:
    """Publish one shard at a time; a valid manifest is the sole cache hit."""

    def __init__(
        self, root: Path, budget: ResourceBudget | None = None, *, scratch_dir: Path | None = None
    ) -> None:
        self.root = Path(root)
        self.budget = budget or ResourceBudget()
        self.shards_root = (
            Path(scratch_dir) if scratch_dir is not None else self.root / "var" / "shards"
        )
        self.quarantine_root = self.root / "var" / "quarantine"

    def destination(self, shard: PlannedShard) -> Path:
        return self.shards_root / shard.stage_id / shard.shard_id.replace(":", "-")

    @staticmethod
    def _declared_files(outputs: Sequence[Path] | None) -> list[Path] | None:
        """Expand declared artifact directories to their material files.

        Stage adapters commonly return a chunk directory.  The completion
        manifest must still hash every nested file, rather than treating that
        directory itself as an invalid file output.
        """

        if outputs is None:
            return None
        files: list[Path] = []
        for output in outputs:
            path = Path(output)
            if path.is_dir():
                files.extend(child for child in sorted(path.rglob("*")) if child.is_file())
            else:
                files.append(path)
        return files

    def inspect(self, shard: PlannedShard, *, quarantine_invalid: bool = False) -> ShardResult:
        """Read validity without mutation unless an executor is replacing it."""
        destination = self.destination(shard)
        if not destination.exists():
            return ShardResult(shard.shard_id, "missing", destination, None)
        try:
            manifest = validate_manifest(destination)
            if manifest.analysis_id != shard.analysis_id or manifest.stage_id != shard.stage_id:
                raise ValueError("published artifact does not match the frozen shard")
            return ShardResult(shard.shard_id, "reused", destination, manifest)
        except (OSError, ValueError, FileNotFoundError) as exc:
            if not quarantine_invalid:
                return ShardResult(shard.shard_id, "invalid", destination, None)
            moved = quarantine(destination, self.quarantine_root, str(exc))
            return ShardResult(shard.shard_id, "quarantined", destination, None, moved)

    def execute(
        self,
        shard: PlannedShard,
        handler: Callable[[Path, Telemetry], Sequence[Path] | None],
        *,
        inputs: dict[str, str] | None = None,
        execution_id: str,
        resume: bool = True,
    ) -> ShardResult:
        existing = self.inspect(shard, quarantine_invalid=True)
        if resume and existing.status == "reused":
            return existing
        staging = new_staging_directory(
            self.shards_root / ".staging", shard.shard_id.replace(":", "-")
        )
        telemetry = Telemetry()
        try:
            with telemetry.phase("kernel"):
                outputs = handler(staging, telemetry)
            declared = self._declared_files(outputs)
            manifest = make_manifest(
                staging,
                stage_id=shard.stage_id,
                analysis_id=shard.analysis_id,
                execution_id=execution_id,
                producer_fingerprint=shard.producer_fingerprint,
                seed_schema_version=shard.seed_schema_version,
                inputs=inputs,
                telemetry=telemetry.record(),
                paths=declared,
            )
            destination = self.destination(shard)
            if destination.exists():
                quarantine(
                    destination,
                    self.quarantine_root,
                    "recomputed shard replaces invalid/incomplete output",
                )
            published = publish_directory(staging, destination, manifest)
            return ShardResult(shard.shard_id, "recomputed", destination, published)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def execute_many(
        self,
        requests: Sequence[
            tuple[
                PlannedShard,
                Callable[[Path, Telemetry], Sequence[Path] | None],
                dict[str, str] | None,
                str,
                bool,
            ]
        ],
    ) -> list[ShardResult]:
        """Run independent same-stage shards with the approved worker cap.

        Dependency ordering remains the planner's responsibility.  NumPy/SciPy
        kernels release the GIL; callers set BLAS/OpenMP to one before process
        start, so two shard workers do not multiply backend threads.
        """

        def run(item) -> ShardResult:
            if len(item) == 6:
                shard, handler, context, inputs, execution_id, resume = item
                return self.execute(
                    shard,
                    lambda out, telemetry: _context_handler(handler, context, out, telemetry),
                    inputs=inputs,
                    execution_id=execution_id,
                    resume=resume,
                )
            shard, handler, inputs, execution_id, resume = item
            return self.execute(
                shard, handler, inputs=inputs, execution_id=execution_id, resume=resume
            )

        if self.budget.workers == 1 or len(requests) < 2:
            return [run(item) for item in requests]
        if all(len(item) == 6 for item in requests):
            with ProcessPoolExecutor(max_workers=self.budget.workers) as pool:
                return list(
                    pool.map(
                        _process_request,
                        [self.root] * len(requests),
                        [self.shards_root] * len(requests),
                        list(requests),
                    )
                )
        with ThreadPoolExecutor(
            max_workers=self.budget.workers, thread_name_prefix="wba-shard"
        ) as pool:
            return list(pool.map(run, requests))
