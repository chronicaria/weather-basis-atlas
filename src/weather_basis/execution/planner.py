"""Frozen shard plans whose scientific identity excludes execution settings."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from weather_basis.provenance.ids import canonical_json, content_id, file_sha256

_BOOK_STAGES = {
    "payoffs.build",
    "portfolios.evaluate",
    "portfolios.optimize",
    "quotes.build",
    "cases.build",
    "site.build",
    "release.verify",
}


def _stage_inputs(stage_id, request, inputs):
    result = dict(inputs)
    if stage_id not in _BOOK_STAGES and request.get("book_path"):
        result.pop(str(request["book_path"]), None)
    return result


@dataclass(frozen=True)
class PlannedShard:
    stage_id: str
    coordinates: dict[str, Any]
    analysis_id: str
    producer_fingerprint: str
    seed_schema_version: str = "v2-seed-1"

    @property
    def shard_id(self) -> str:
        return content_id({"analysis_id": self.analysis_id, "coordinates": self.coordinates})


@dataclass(frozen=True)
class ExecutionPlan:
    schema_version: str
    interface_revision: int
    shards: tuple[PlannedShard, ...]
    scientific_request: dict[str, Any]
    input_artifacts: dict[str, str]
    stage_order: tuple[str, ...] = ()
    missing_inputs: tuple[str, ...] = ()
    execution_profile: dict[str, Any] | None = None
    producer_fingerprints: dict[str, str] | None = None

    @property
    def plan_id(self) -> str:
        return content_id(
            {
                "schema_version": self.schema_version,
                "interface_revision": self.interface_revision,
                "shards": [asdict(item) for item in self.shards],
                "scientific_request": self.scientific_request,
                "input_artifacts": self.input_artifacts,
                "stage_order": self.stage_order,
                "missing_inputs": self.missing_inputs,
                "producer_fingerprints": self.producer_fingerprints,
            }
        )


def plan_shards(
    *,
    stage_id: str,
    coordinates: list[dict[str, Any]],
    scientific_request: dict[str, Any],
    input_artifacts: dict[str, str],
    producer_fingerprint: str,
    seed_schema_version: str = "v2-seed-1",
) -> ExecutionPlan:
    """Freeze coordinate-specific analysis IDs from science, inputs and producer.

    Worker count, memory budget and cache directory intentionally are absent.
    """

    ordered = sorted(coordinates, key=lambda item: content_id(item))
    shards = tuple(
        PlannedShard(
            stage_id=stage_id,
            coordinates=item,
            analysis_id=content_id(
                {
                    "schema_version": "2.0",
                    "stage_id": stage_id,
                    "coordinates": item,
                    "scientific_request": scientific_request,
                    "input_artifacts": dict(sorted(input_artifacts.items())),
                    "producer_fingerprint": producer_fingerprint,
                    "seed_schema_version": seed_schema_version,
                }
            ),
            producer_fingerprint=producer_fingerprint,
            seed_schema_version=seed_schema_version,
        )
        for item in ordered
    )
    return ExecutionPlan(
        schema_version="2.0",
        interface_revision=1,
        shards=shards,
        scientific_request=scientific_request,
        input_artifacts=dict(sorted(input_artifacts.items())),
    )


def _definition(registry: Mapping[str, Any], stage_id: str) -> Any:
    try:
        return registry[stage_id]
    except KeyError as exc:
        raise ValueError(f"unknown V2 stage: {stage_id}") from exc


def _ordered_stages(registry: Mapping[str, Any], stage_id: str) -> tuple[str, ...]:
    result: list[str] = []
    active: set[str] = set()

    def visit(candidate: str) -> None:
        if candidate in result:
            return
        if candidate in active:
            raise ValueError(f"cyclic V2 stage dependency at {candidate}")
        active.add(candidate)
        definition = _definition(registry, candidate)
        for dependency in getattr(definition, "dependencies", ()):
            visit(str(dependency))
        active.remove(candidate)
        result.append(candidate)

    visit(stage_id)
    return tuple(result)


def _producer_fingerprint(root: Path, definition: Any) -> str:
    paths = tuple(getattr(definition, "producer_paths", ()))
    records: dict[str, str] = {}
    for name in paths:
        path = root / name
        if not path.is_file():
            records[str(name)] = "missing"
        else:
            records[str(name)] = file_sha256(path)
    return content_id(records)


def _declared_inputs(
    root: Path, request: Mapping[str, Any], vintage: Mapping[str, Any]
) -> tuple[dict[str, str], tuple[str, ...]]:
    raw = list(request.get("input_paths", ())) + list(vintage.get("input_paths", ()))
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for name in sorted({str(item) for item in raw}):
        path = Path(name)
        path = path if path.is_absolute() else root / path
        if path.is_file():
            resolved[name] = file_sha256(path)
        else:
            missing.append(name)
    return resolved, tuple(missing)


def create_plan(
    root: Path,
    registry: Mapping[str, Any],
    stage: str,
    research: Mapping[str, Any],
    request: Mapping[str, Any],
    vintage: Mapping[str, Any],
    profile: Mapping[str, Any] | None = None,
) -> ExecutionPlan:
    """Resolve a no-execution plan and explicitly report unavailable inputs."""

    base = Path(root).resolve()
    stage_order = _ordered_stages(registry, stage)
    inputs, missing = _declared_inputs(base, request, vintage)
    coordinates = request.get("coordinates", [{}])
    if not isinstance(coordinates, list) or not all(isinstance(item, dict) for item in coordinates):
        raise ValueError("request.coordinates must be a list of coordinate objects")
    producer_fingerprints = {
        stage_id: _producer_fingerprint(base, _definition(registry, stage_id))
        for stage_id in stage_order
    }
    seed_schema_version = str(research.get("seed_schema_version", "v2-seed-1"))
    frozen_vintage_id = content_id(dict(vintage))
    shards: list[PlannedShard] = []
    semantic_outputs: dict[str, list[str]] = {}
    for stage_id in stage_order:
        definition = _definition(registry, stage_id)
        fields = tuple(getattr(definition, "config_fields", ()))
        stage_research = {field: research.get(field) for field in fields}
        # Full and representative execution deliberately materialize different
        # path counts. This is scientific scope, unlike the worker/memory
        # profile, and must not collide in the cache.
        stage_request = {"mode": request.get("mode")}
        stage_inputs = _stage_inputs(stage_id, request, inputs)
        if stage_id in _BOOK_STAGES:
            stage_request["objective"] = request.get("objective", "es")
        dependency_ids = {
            dependency: semantic_outputs.get(str(dependency), [])
            for dependency in getattr(definition, "dependencies", ())
        }
        stage_shards: list[PlannedShard] = []
        for coordinate in sorted(coordinates, key=content_id):
            analysis_id = content_id(
                {
                    "schema_version": "2.0",
                    "stage_id": stage_id,
                    "coordinates": coordinate,
                    "research": stage_research,
                    "vintage_id": frozen_vintage_id,
                    "input_artifacts": dict(sorted(stage_inputs.items())),
                    "request_parameters": stage_request,
                    "dependency_analysis_ids": dependency_ids,
                    "producer_fingerprint": producer_fingerprints[stage_id],
                    "seed_schema_version": seed_schema_version,
                }
            )
            stage_shards.append(
                PlannedShard(
                    stage_id=stage_id,
                    coordinates=coordinate,
                    analysis_id=analysis_id,
                    producer_fingerprint=producer_fingerprints[stage_id],
                    seed_schema_version=seed_schema_version,
                )
            )
        semantic_outputs[stage_id] = [item.analysis_id for item in stage_shards]
        shards.extend(stage_shards)
    return ExecutionPlan(
        schema_version="2.0",
        interface_revision=1,
        shards=tuple(shards),
        scientific_request={
            "research": dict(research),
            "request": dict(request),
            "vintage": dict(vintage),
        },
        input_artifacts=inputs,
        stage_order=stage_order,
        missing_inputs=missing,
        execution_profile=dict(profile or {}),
        producer_fingerprints=producer_fingerprints,
    )


def write_plan(plan: ExecutionPlan, path: Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(asdict(plan)) + "\n", encoding="utf-8")
    return target


def read_plan(path: Path) -> ExecutionPlan:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    raw["shards"] = tuple(PlannedShard(**item) for item in raw["shards"])
    raw["stage_order"] = tuple(raw.get("stage_order", ()))
    raw["missing_inputs"] = tuple(raw.get("missing_inputs", ()))
    return ExecutionPlan(**raw)


def assert_plan_current(
    plan: ExecutionPlan,
    root: Path,
    registry: Mapping[str, Any],
    research: Mapping[str, Any],
    request: Mapping[str, Any],
    vintage: Mapping[str, Any],
) -> None:
    """Refuse frozen-plan execution after science, inputs or producer drift."""

    expected = create_plan(root, registry, plan.stage_order[-1], research, request, vintage)
    if plan.plan_id != expected.plan_id:
        raise ValueError(
            "frozen plan drift: scientific request, inputs, coordinates or producer changed"
        )
    if plan.missing_inputs:
        raise FileNotFoundError(
            f"frozen plan has missing dependencies: {', '.join(plan.missing_inputs)}"
        )


def run_plan(
    plan: ExecutionPlan,
    root: Path,
    registry: Mapping[str, Any],
    *,
    execution_id: str,
    budget: Any | None = None,
    resume: bool = True,
) -> list[Any]:
    """Execute frozen target shards through registry handlers, never replanning.

    The application owns ``StageDefinition``.  This intentionally relies only
    on its documented ``handler(context, out_directory)`` attributes so the
    execution layer does not introduce a competing stage registry.
    """

    from types import SimpleNamespace

    from .scheduler import ResourceBudget, ShardExecutor

    if plan.missing_inputs:
        raise FileNotFoundError(
            f"frozen plan has missing dependencies: {', '.join(plan.missing_inputs)}"
        )
    assert_plan_current(
        plan,
        root,
        registry,
        plan.scientific_request["research"],
        plan.scientific_request["request"],
        plan.scientific_request["vintage"],
    )
    scratch = (plan.execution_profile or {}).get("scratch_dir")
    scratch_path = Path(root) / scratch if scratch and not Path(scratch).is_absolute() else scratch
    executor = ShardExecutor(
        Path(root), budget if budget is not None else ResourceBudget(), scratch_dir=scratch_path
    )
    results: list[Any] = []
    produced: dict[str, str] = {}
    produced_directories: dict[str, list[Path]] = {}
    for stage_id in plan.stage_order:
        stage_shards = [shard for shard in plan.shards if shard.stage_id == stage_id]
        definition = _definition(registry, stage_id)
        handler = getattr(definition, "handler", None)
        if not callable(handler):
            raise TypeError(f"stage {stage_id} has no callable handler")
        dependency_artifacts = {
            key: value
            for key, value in produced.items()
            if key.split("/", 1)[0] in set(getattr(definition, "dependencies", ()))
        }
        dependency_directories = {
            stage_id: directories
            for stage_id, directories in produced_directories.items()
            if stage_id in set(getattr(definition, "dependencies", ()))
        }
        resolved_inputs = {
            **_stage_inputs(stage_id, plan.scientific_request["request"], plan.input_artifacts),
            **dependency_artifacts,
        }
        requests = []
        for shard in stage_shards:
            context = SimpleNamespace(
                root=Path(root),
                research=plan.scientific_request["research"],
                request=plan.scientific_request["request"],
                vintage=plan.scientific_request["vintage"],
                input_artifacts=resolved_inputs,
                dependency_artifacts=dependency_artifacts,
                dependency_directories=dependency_directories,
                analysis_id=shard.analysis_id,
                execution_id=execution_id,
                coordinates=shard.coordinates,
            )

            requests.append((shard, handler, context, resolved_inputs, execution_id, resume))
        stage_results = executor.execute_many(requests)
        results.extend(stage_results)
        for shard, result in zip(stage_shards, stage_results, strict=True):
            if result.manifest is not None:
                coordinate_key = content_id(shard.coordinates)
                produced[f"{shard.stage_id}/{coordinate_key}"] = result.manifest.artifact_id
                produced_directories.setdefault(shard.stage_id, []).append(result.directory)
    return results
