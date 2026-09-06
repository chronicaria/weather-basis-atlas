"""Parse user-facing files once; kernels receive validated typed settings."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from weather_basis.schemas.config import ExecutionProfile, ResearchConfig, RunRequest
from weather_basis.schemas.vintages import VintageLock


def load_mapping(path: Path):
    with Path(path).open() as stream:
        value = json.load(stream) if Path(path).suffix == ".json" else yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected object in {path}")
    return value


def load_request_files(
    root, *, spec, vintage, profile, request=None, stage=None, pairs=(), origins=(), counties=()
):
    research = ResearchConfig.from_dict(load_mapping(root / spec))
    vintage_record = VintageLock.from_dict(load_mapping(root / vintage))
    profile_path = Path(profile)
    if profile_path.suffix not in (".yaml", ".json"):
        profile_path = Path("config/profiles") / f"{profile}.yaml"
    execution = ExecutionProfile.from_dict(load_mapping(root / profile_path))
    if request:
        request_data = load_mapping(root / request)
        if stage and request_data.get("stage") not in (None, stage):
            raise ValueError("Request and --stage disagree")
        request_data["stage"] = stage or request_data["stage"]
    else:
        request_data = {"schema_version": "2.0", "stage": stage, "mode": execution.name}
    for key, values in (("pairs", pairs), ("origins", origins), ("county_panel", counties)):
        if values:
            if request_data.get(key) and tuple(request_data[key]) != tuple(values):
                raise ValueError(f"Conflicting {key} selectors")
            request_data[key] = list(values)
    run_request = RunRequest.from_dict(request_data)
    if not run_request.stage:
        raise ValueError("A stage is required")
    if not set(run_request.pairs) <= set(research.pairs):
        raise ValueError("Requested pair outside research specification")
    from weather_basis.application.stages import stage_registry, validate_selectors

    try:
        definition = stage_registry(root)[run_request.stage]
    except KeyError as exc:
        raise ValueError(f"unknown V2 stage: {run_request.stage}") from exc
    validate_selectors(run_request, definition)
    # The current national evaluator has these audited bounds embedded in its
    # domain adapter.  Refuse alternate config values until that adapter accepts
    # them, rather than recording a plan that silently ignores the request.
    if run_request.stage == "atlas.evaluate":
        required = {"first_test_year": 1981, "last_test_year": 2025, "min_train": 15}
        changed = [name for name, value in required.items() if getattr(research, name) != value]
        if changed:
            raise ValueError(
                "atlas.evaluate only supports audited research values: "
                + ", ".join(f"{name}={required[name]}" for name in changed)
            )
    paths = {
        "spec": str(spec),
        "vintage": str(vintage),
        "profile": str(profile_path),
        "request": str(request) if request else None,
    }
    return research, vintage_record, execution, run_request, paths


def execution_request(root: Path, request: RunRequest) -> dict:
    """Explicit adapter: resolved file paths/coordinates are planner metadata, not config fields."""
    result = request.to_dict()
    result["coordinates"] = [
        {
            "pairs": list(request.pairs),
            "origins": list(request.origins),
            "county_panel": list(request.county_panel),
        }
    ]
    if request.mode == "fixture":
        inputs = [
            "tests/fixtures/v2/portfolio_hand_cases.json",
            "tests/fixtures/v2/policy_evaluation.json",
        ]
    else:
        inputs = [
            "config/data_vintage.yaml",
            "config/defaults.yaml",
            "data/metadata/counties.csv",
            "data/metadata/station_registry.csv",
            "data/panel/dates.npy",
            "data/panel/fips.npy",
            "data/panel/station_ids.npy",
            "data/panel/tavg_f32.npy",
            "data/panel/stations_tbar_f32.npy",
        ]
        inputs += [
            str(p.relative_to(root)) for p in sorted((root / "results/indices").glob("*.parquet"))
        ]
        inputs += [
            str(p.relative_to(root)) for p in sorted((root / "data/manifests").rglob("*.json"))
        ]
    if request.book_path:
        inputs.append(request.book_path)
    result["input_paths"] = inputs
    return result
