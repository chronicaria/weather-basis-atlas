"""The stable wba v2 command namespace; expensive work requires a frozen plan."""

from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path

from weather_basis.provenance.ids import canonical_json


def register_parser(commands):
    v2 = commands.add_parser("v2", help="Typed, reproducible V2 workbench")
    actions = v2.add_subparsers(dest="v2_command", required=True)
    for name in ("plan", "bench"):
        parser = actions.add_parser(name)
        parser.add_argument("--stage", required=True)
        parser.add_argument("--spec", type=Path, default=Path("config/research/v2.yaml"))
        parser.add_argument("--vintage", type=Path, default=Path("config/vintages/v1-frozen.yaml"))
        parser.add_argument("--profile", default="fixture" if name == "plan" else "representative")
        parser.add_argument("--request", type=Path)
        parser.add_argument("--out", type=Path, required=True)
        parser.add_argument("--workers", type=int)
        parser.add_argument("--memory-gib", type=float)
        parser.add_argument("--pair", action="append", default=[])
        parser.add_argument("--origin", action="append", type=int, default=[])
        parser.add_argument("--county-panel", type=Path)
    run = actions.add_parser("run")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--resume", action="store_true", default=True)
    run.add_argument("--force", action="store_true")
    run.add_argument("--workers", type=int)
    run.add_argument("--memory-gib", type=float)
    verify = actions.add_parser("verify")
    verify.add_argument("--gate", action="append", choices=[f"G{i}" for i in range(9)], default=[])
    verify.add_argument("--plan", type=Path)
    verify.add_argument(
        "--candidate",
        type=Path,
        help="Candidate-evidence JSON for acceptance validation; does not create evidence",
    )
    verify.add_argument(
        "--seed-validation",
        type=Path,
        nargs=2,
        metavar=("PRIMARY", "SECONDARY"),
        help="Compare two explicit frozen R2j manifests; no scenario generation or tournament",
    )
    verify.add_argument("--out", type=Path, default=Path("results/v2/validation/verification.json"))
    release = actions.add_parser("release").add_subparsers(dest="release_command", required=True)
    build = release.add_parser("build")
    build.add_argument("--lock", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    for name in ("verify", "inspect"):
        parser = release.add_parser(name)
        parser.add_argument("--bundle", type=Path, required=True)
        if name == "verify":
            parser.add_argument(
                "--print-manifest",
                action="store_true",
                help="Print the full file inventory (tens of MB) instead of a summary",
            )
    rollback = release.add_parser("rollback")
    rollback.add_argument("--bundle", type=Path, required=True)
    rollback.add_argument(
        "--target",
        type=Path,
        required=True,
        help="Explicit local recovery target; no implicit production deploy",
    )
    serve = actions.add_parser("serve")
    serve.add_argument("--bundle", type=Path, required=True)
    serve.add_argument("--port", type=int, default=8765)


def _jsonable(value):
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _new_plan(args, root):
    from weather_basis.application.requests import execution_request, load_request_files
    from weather_basis.application.stages import stage_registry
    from weather_basis.execution.planner import create_plan, write_plan

    counties = json.loads(args.county_panel.read_text()) if args.county_panel else []
    if isinstance(counties, dict):
        counties = counties.get("fips")
    if not isinstance(counties, list) or not all(isinstance(value, str) for value in counties):
        raise ValueError(
            "--county-panel must contain a JSON array of FIPS strings or {'fips': [...]}"
        )
    research, vintage, profile, request, paths = load_request_files(
        root,
        spec=args.spec,
        vintage=args.vintage,
        profile=args.profile,
        request=args.request,
        stage=args.stage,
        pairs=args.pair,
        origins=args.origin,
        counties=counties,
    )
    profile_dict = profile.to_dict()
    if args.workers is not None:
        profile_dict["workers"] = args.workers
    if args.memory_gib is not None:
        profile_dict["memory_gib"] = args.memory_gib
    # Validate execution settings at plan time so an unsupported override is
    # never preserved in a plan and then ignored until a later run.
    from weather_basis.execution.scheduler import ResourceBudget

    ResourceBudget(
        workers=profile_dict["workers"], memory_gib=profile_dict["memory_gib"]
    )
    resolved = execution_request(root, request)
    # File locators are retained so later invocation re-reads current contents, not stale snapshots.
    resolved["source_files"] = paths
    plan = create_plan(
        root,
        stage_registry(root),
        request.stage,
        research.to_dict(),
        resolved,
        vintage.to_dict(),
        profile_dict,
    )
    output = args.out if args.v2_command == "plan" else args.out / "plan.json"
    write_plan(plan, output)
    return plan, output


def _execute(plan, root, args):
    from weather_basis.application.requests import load_mapping
    from weather_basis.application.stages import stage_registry
    from weather_basis.execution.planner import assert_plan_current, run_plan
    from weather_basis.execution.scheduler import ResourceBudget
    from weather_basis.schemas.config import ResearchConfig, RunRequest
    from weather_basis.schemas.vintages import VintageLock

    files = plan.scientific_request["request"]["source_files"]
    research = ResearchConfig.from_dict(load_mapping(root / files["spec"])).to_dict()
    vintage = VintageLock.from_dict(load_mapping(root / files["vintage"])).to_dict()
    request = plan.scientific_request["request"]
    if files["request"]:
        actual = RunRequest.from_dict(load_mapping(root / files["request"])).to_dict()
        if any(canonical_json(actual[key]) != canonical_json(request[key]) for key in actual):
            raise ValueError("Frozen request file changed; emit a new plan")
    registry = stage_registry(root)
    assert_plan_current(plan, root, registry, research, request, vintage)
    profile = plan.execution_profile or {}
    budget = ResourceBudget(
        workers=args.workers if args.workers is not None else profile.get("workers", 1),
        memory_gib=(
            args.memory_gib if args.memory_gib is not None else profile.get("memory_gib", 12)
        ),
    )
    results = run_plan(
        plan,
        root,
        registry,
        execution_id=f"execution:{uuid.uuid4()}",
        budget=budget,
        resume=not getattr(args, "force", False),
    )
    return {"plan_id": plan.plan_id, "scope": request["mode"], "stages": _jsonable(results)}


def main(args, root: Path) -> int:
    try:
        if args.v2_command in ("plan", "bench"):
            plan, path = _new_plan(args, root)
            if args.v2_command == "plan":
                result = {
                    "plan_id": plan.plan_id,
                    "plan": str(path),
                    "stage_order": plan.stage_order,
                    "shards": len(plan.shards),
                    "missing_inputs": plan.missing_inputs,
                    "execution_profile": plan.execution_profile,
                }
            else:
                result = _execute(plan, root, args)
                (args.out / "benchmark.json").write_text(canonical_json(result) + "\n")
        elif args.v2_command == "run":
            from weather_basis.execution.planner import read_plan

            result = _execute(read_plan(args.plan), root, args)
        elif args.v2_command == "verify":
            from .verification import verify_gates

            result = verify_gates(
                root,
                args.gate,
                plan_path=args.plan,
                candidate_path=args.candidate,
                seed_validation_paths=tuple(args.seed_validation or ()),
                out=args.out,
            )
            print(canonical_json(result))
            return 0 if result["status"] == "passed" else 4
        elif args.v2_command == "release":
            from weather_basis.publishing.release import (
                build_release,
                inspect_release,
                rollback_release,
                verify_release,
            )

            if args.release_command == "build":
                result = build_release(root, args.lock, args.out)
            elif args.release_command == "rollback":
                result = rollback_release(args.bundle, args.target)
            elif args.release_command == "inspect":
                result = inspect_release(args.bundle)
            else:
                # The manifest is one line of tens of megabytes: summarise unless asked.
                result = verify_release(args.bundle)
                if not args.print_manifest:
                    files = result.get("files", [])
                    result = {
                        **{key: value for key, value in result.items() if key != "files"},
                        "verified": "passed",
                        "file_count": len(files),
                        "total_bytes": sum(record.get("bytes", 0) for record in files),
                    }
        elif args.v2_command == "serve":
            from functools import partial
            from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

            from weather_basis.publishing.release import verify_release

            verify_release(args.bundle)
            server = ThreadingHTTPServer(
                ("127.0.0.1", args.port),
                partial(SimpleHTTPRequestHandler, directory=str(args.bundle.resolve())),
            )
            print(f"Serving verified bundle at http://127.0.0.1:{args.port}", flush=True)
            server.serve_forever()
            return 0
        else:
            raise ValueError("Unknown V2 command")
        print(canonical_json(_jsonable(result)))
        return 0
    except FileNotFoundError as exc:
        print(canonical_json({"status": "missing_dependency", "reason": str(exc)}))
        return 3
    except (ValueError, TypeError) as exc:
        print(canonical_json({"status": "invalid_request", "reason": str(exc)}))
        return 2
    except RuntimeError as exc:
        print(canonical_json({"status": "runtime_failure", "reason": str(exc)}))
        return 5
