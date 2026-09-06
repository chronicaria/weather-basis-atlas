"""Executed V2 gate evidence, explicitly scoped to fixture/representative/full artifacts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from weather_basis.provenance.ids import canonical_json, content_id, file_sha256

GATE_TESTS = {
    "G0": ["tests/unit/test_v2_schemas.py", "tests/site/test_v2_state.py"],
    "G1": ["tests/unit/test_v2_policies.py", "tests/unit/test_v2_asof.py"],
    "G2": [
        "tests/unit/test_v2_pricing.py",
        "tests/unit/test_v2_registry.py",
        "tests/unit/test_v2_portfolio.py",
    ],
    "G3": ["tests/unit/test_v2_scenarios.py", "tests/unit/test_v2_schemas.py"],
    "G4": ["tests/unit/test_v2_portfolio.py"],
    "G5": ["tests/unit/test_v2_research.py", "tests/unit/test_v2_research_publishing.py"],
    "G6": ["tests/site/test_v2_state.py", "tests/unit/test_v2_research_publishing.py"],
    "G7": ["tests/unit/test_v2_execution.py"],
    "G8": ["tests/unit/test_v2_release.py"],
}


def verify_gates(
    root: Path, gates, *, plan_path=None, candidate_path=None, seed_validation_paths=(), out: Path
):
    from weather_basis.application.stages import stage_registry
    from weather_basis.execution.planner import assert_plan_current, read_plan
    from weather_basis.execution.scheduler import ShardExecutor

    selected = gates or list(GATE_TESTS)
    if not set(selected) <= GATE_TESTS.keys():
        raise ValueError("Unknown V2 gate")
    scope, plan_id, artifacts = "focused_checks", None, []
    plan_status = None
    if plan_path:
        plan = read_plan(plan_path)
        scope = plan.scientific_request["request"]["mode"]
        plan_id = plan.plan_id
        assert_plan_current(
            plan,
            root,
            stage_registry(root),
            plan.scientific_request["research"],
            plan.scientific_request["request"],
            plan.scientific_request["vintage"],
        )
        profile = plan.execution_profile or {}
        executor = ShardExecutor(root)
        if "scratch_dir" in profile:
            executor.shards_root = root / profile["scratch_dir"]
        for shard in plan.shards:
            inspected = executor.inspect(shard)
            artifacts.append(
                {
                    "stage": shard.stage_id,
                    "analysis_id": shard.analysis_id,
                    "status": inspected.status,
                    "path": str(inspected.directory),
                    "artifact_id": inspected.manifest.artifact_id if inspected.manifest else None,
                }
            )
        plan_status = "passed" if all(a["status"] == "reused" for a in artifacts) else "failed"
    tests = sorted({test for gate in selected for test in GATE_TESTS[gate]})
    command = [sys.executable, "-m", "pytest", "-q", *tests]
    process = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    log = out.with_suffix(".pytest.txt")
    log.write_text(process.stdout + process.stderr)
    records = []
    for gate in selected:
        state = "passed" if process.returncode == 0 and plan_status != "failed" else "failed"
        records.append(
            {
                "gate": gate,
                "status": state,
                "scope": scope,
                "tests": GATE_TESTS[gate],
                "check_log": str(log),
                "limitation": (
                    "Focused/fixture evidence does not certify national science, "
                    "browser journeys, or public deployment."
                ),
            }
        )
    report = {
        "schema_version": "2.0",
        "plan_id": plan_id,
        "scope": scope,
        "status": "passed" if all(r["status"] == "passed" for r in records) else "failed",
        "gates": records,
        "artifacts": artifacts,
        "command": command,
        "returncode": process.returncode,
        "log_sha256": file_sha256(log),
        "national_release_acceptance": "pending_explicit_full_candidate_evidence",
    }
    if candidate_path is not None:
        from weather_basis.application.acceptance import verify_candidate

        report["candidate"] = verify_candidate(root, candidate_path, selected)
        if report["candidate"]["status"] != "passed":
            report["status"] = "failed"
        report["national_release_acceptance"] = "see_scoped_candidate_and_external_evidence"
    if seed_validation_paths:
        from weather_basis.pricing.payoff_batch import verify_seed_artifacts

        if len(seed_validation_paths) != 2:
            raise ValueError("Seed validation requires primary and secondary artifact manifests")
        report["seed_validation"] = verify_seed_artifacts(*seed_validation_paths)
        if report["seed_validation"].get("status") not in {"passed", "complete"}:
            report["status"] = "failed"
    report["report_id"] = content_id(report, prefix="verification")
    out.write_text(canonical_json(report) + "\n")
    return report
