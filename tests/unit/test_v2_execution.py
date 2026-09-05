"""B08 content identity, atomic completion, resume and corruption checks."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from weather_basis.application.stages import stage_registry
from weather_basis.execution.planner import assert_plan_current, create_plan, plan_shards
from weather_basis.execution.scheduler import ResourceBudget, ShardExecutor
from weather_basis.models.daily import DailyFit
from weather_basis.models.fit_cache import FitCache, FitRequest, numerical_environment
from weather_basis.models.residual import ARFit, LogVarFit
from weather_basis.provenance.ids import canonical_json, content_id, file_sha256


def test_canonical_ids_are_key_order_stable_and_reject_nonfinite(tmp_path: Path) -> None:
    assert canonical_json({"b": 2, "a": [True, None]}) == '{"a":[true,null],"b":2}'
    assert content_id({"b": 2, "a": 1}) == content_id({"a": 1, "b": 2})
    with pytest.raises(ValueError, match="non-finite"):
        canonical_json({"value": float("nan")})
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"v2")
    assert (
        file_sha256(payload) == "fb04dcb6970e4c3d1873de51fd5a50d7bb46b3383113602665c350ec40b5f990"
    )


def test_resume_quarantines_corruption_and_recomputes_only_affected_shard(tmp_path: Path) -> None:
    plan = plan_shards(
        stage_id="tournament.execute",
        coordinates=[{"pair": "CDD-07", "origin": 1991}, {"pair": "HDD-01", "origin": 2022}],
        scientific_request={"M": 12, "cutoff": "frozen"},
        input_artifacts={"panel": "sha256:panel"},
        producer_fingerprint="sha256:producer",
    )
    executor = ShardExecutor(tmp_path)
    calls: list[str] = []

    def handler(out: Path, _telemetry: object) -> list[Path]:
        calls.append(out.name)
        result = out / "result.txt"
        result.write_text("fixed kernel output\n", encoding="utf-8")
        return [result]

    first = executor.execute(plan.shards[0], handler, execution_id="sha256:run-1")
    assert first.status == "recomputed"
    # This simulates interruption after the first accepted shard. Resume has no
    # work for it and executes only the second frozen coordinate.
    resumed_first = executor.execute(plan.shards[0], handler, execution_id="sha256:run-2")
    second = executor.execute(plan.shards[1], handler, execution_id="sha256:run-2")
    assert resumed_first.status == "reused"
    assert second.status == "recomputed"
    assert len(calls) == 2

    (first.directory / "result.txt").write_text("corrupt", encoding="utf-8")
    inspected = executor.inspect(plan.shards[0])
    assert inspected.status == "invalid"
    assert first.directory.exists()
    repaired = executor.execute(plan.shards[0], handler, execution_id="sha256:run-3")
    assert repaired.status == "recomputed"
    assert len(calls) == 3
    assert list((tmp_path / "var" / "quarantine").iterdir())


@pytest.mark.parametrize("declare_directory", [True, False])
def test_executor_hashes_all_files_when_handler_declares_chunk_directory(
    tmp_path: Path, declare_directory: bool
) -> None:
    shard = plan_shards(
        stage_id="scenarios.build",
        coordinates=[{}],
        scientific_request={"paths": 2},
        input_artifacts={},
        producer_fingerprint="sha256:producer",
    ).shards[0]

    def handler(out: Path, _telemetry: object) -> list[Path] | None:
        chunks = out / "chunks"
        chunks.mkdir()
        (chunks / "county.npz").write_bytes(b"county")
        (chunks / "stations.npz").write_bytes(b"stations")
        return [chunks] if declare_directory else None

    result = ShardExecutor(tmp_path).execute(shard, handler, execution_id="execution:chunks")
    assert result.status == "recomputed"
    assert result.manifest is not None
    assert [file.path for file in result.manifest.files] == [
        "chunks/county.npz",
        "chunks/stations.npz",
    ]


def test_worker_count_is_not_scientific_identity() -> None:
    common = dict(
        stage_id="tournament.execute",
        coordinates=[{"pair": "HDD-01", "origin": 2022}],
        scientific_request={"M": 12},
        input_artifacts={"panel": "sha256:panel"},
        producer_fingerprint="sha256:producer",
    )
    assert plan_shards(**common).plan_id == plan_shards(**common).plan_id
    assert ResourceBudget().workers == 1
    assert ResourceBudget(workers=2, memory_gib=8).workers == 2
    with pytest.raises(ValueError, match="one or two"):
        ResourceBudget(workers=3)


def test_plan_captures_dependency_producers_and_rejects_relevant_drift(tmp_path: Path) -> None:
    (tmp_path / "ancestor.py").write_text("v1\n", encoding="utf-8")
    (tmp_path / "target.py").write_text("v1\n", encoding="utf-8")

    class Stage:
        def __init__(self, dependencies: tuple[str, ...], producer_paths: tuple[str, ...]) -> None:
            self.dependencies = dependencies
            self.producer_paths = producer_paths
            self.config_fields = ("model",)

    registry = {
        "inputs.audit": Stage((), ("ancestor.py",)),
        "tournament.execute": Stage(("inputs.audit",), ("target.py",)),
    }
    research = {"model": "R2", "workers": 1}
    request = {"coordinates": [{"pair": "HDD-01"}]}
    vintage = {"lock": "frozen"}
    plan = create_plan(tmp_path, registry, "tournament.execute", research, request, vintage)
    assert plan.stage_order == ("inputs.audit", "tournament.execute")
    assert [item.stage_id for item in plan.shards] == ["inputs.audit", "tournament.execute"]
    assert_plan_current(plan, tmp_path, registry, research, request, vintage)
    (tmp_path / "ancestor.py").write_text("v2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen plan drift"):
        assert_plan_current(plan, tmp_path, registry, research, request, vintage)


def test_book_compiler_change_invalidates_only_portfolio_descendants(tmp_path: Path) -> None:
    book = tmp_path / "config/books/fixture.json"
    book.parent.mkdir(parents=True)
    book.write_text('{"version": 1}\n', encoding="utf-8")
    request = {"coordinates": [{}]}
    research, vintage = {}, {"lock": "frozen"}
    before_registry = stage_registry(tmp_path)
    before = create_plan(
        tmp_path, before_registry, "portfolios.optimize", research, request, vintage
    )
    book.write_text('{"version": 2}\n', encoding="utf-8")
    after_registry = stage_registry(tmp_path)
    after = create_plan(tmp_path, after_registry, "portfolios.optimize", research, request, vintage)

    before_ids = {shard.stage_id: shard.analysis_id for shard in before.shards}
    after_ids = {shard.stage_id: shard.analysis_id for shard in after.shards}
    assert before_ids["inputs.audit"] == after_ids["inputs.audit"]
    assert before_ids["scenarios.build"] == after_ids["scenarios.build"]
    assert before_ids["payoffs.build"] != after_ids["payoffs.build"]
    assert before_ids["portfolios.evaluate"] != after_ids["portfolios.evaluate"]
    assert before_ids["portfolios.optimize"] != after_ids["portfolios.optimize"]


def test_exact_cutoff_fit_cache_reuses_only_identical_support(tmp_path: Path) -> None:
    def request(cutoff: str) -> FitRequest:
        return FitRequest(
            cutoff=cutoff,
            panel_id="sha256:panel",
            series_ids=("01001", "01003"),
            support_hash="sha256:support",
            model_spec={"mean_months": 480, "ar_orders": [1, 2, 3, 5]},
            producer_fingerprint="sha256:daily",
            numerical_environment=numerical_environment(),
        )

    def fit() -> DailyFit:
        return DailyFit(
            mean_coef=np.ones((2, 8)),
            ar=ARFit(
                np.ones((2, 1)),
                np.ones(2, dtype=int),
                np.ones(2),
                np.ones((3, 2)),
                np.ones((2, 2), dtype=bool),
            ),
            logvar=LogVarFit(np.ones((2, 5)), np.ones(2)),
            z=np.ones((3, 2)),
            fit_mask=np.array([True, True, True]),
        )

    cache, calls = FitCache(tmp_path / "cache"), []
    first, reused = cache.get_or_fit(request("2021-02-28"), lambda: calls.append(1) or fit())
    second, reused_second = cache.get_or_fit(
        request("2021-02-28"), lambda: calls.append(2) or fit()
    )
    _, different_cutoff = cache.get_or_fit(request("2021-08-31"), lambda: calls.append(3) or fit())
    assert not reused and reused_second and not different_cutoff
    assert calls == [1, 3]
    assert np.array_equal(first.z, second.z)


def test_scope_objective_and_custom_book_are_part_of_the_correct_cache_identity(tmp_path):
    book = tmp_path / "custom.json"
    book.write_text('{"amount": 1}')
    registry = stage_registry(tmp_path)
    request = {
        "mode": "full",
        "objective": "es",
        "book_path": "custom.json",
        "input_paths": ["custom.json"],
        "coordinates": [{}],
    }

    def identities(**updates):
        plan = create_plan(
            tmp_path, registry, "portfolios.optimize", {}, {**request, **updates}, {}
        )
        return {shard.stage_id: shard.analysis_id for shard in plan.shards}

    baseline = identities()
    changed_scope = identities(mode="representative")
    changed_objective = identities(objective="mse")
    assert changed_scope["scenarios.build"] != baseline["scenarios.build"]
    assert changed_objective["scenarios.build"] == baseline["scenarios.build"]
    assert changed_objective["payoffs.build"] != baseline["payoffs.build"]
    book.write_text('{"amount": 2}')
    changed_book = identities()
    assert changed_book["models.fit"] == baseline["models.fit"]
    assert changed_book["scenarios.build"] == baseline["scenarios.build"]
    assert changed_book["payoffs.build"] != baseline["payoffs.build"]


def test_two_worker_executor_only_parallelizes_independent_shards(tmp_path: Path) -> None:
    plan = plan_shards(
        stage_id="models.fit",
        coordinates=[{"cutoff": "2021-02-28"}, {"cutoff": "2021-08-31"}],
        scientific_request={"model": "R2"},
        input_artifacts={},
        producer_fingerprint="sha256:daily",
    )

    def handler(out: Path, _telemetry: object) -> list[Path]:
        output = out / "fit.txt"
        output.write_text("deterministic fit", encoding="utf-8")
        return [output]

    executor = ShardExecutor(tmp_path, ResourceBudget(workers=2, memory_gib=8))
    results = executor.execute_many(
        [(shard, handler, {}, "execution:two", True) for shard in plan.shards]
    )
    assert [result.status for result in results] == ["recomputed", "recomputed"]
