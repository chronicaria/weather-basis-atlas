"""Real V2 model/scenario stage adapters."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from weather_basis.application.requests import load_mapping
from weather_basis.provenance.ids import canonical_json, content_id, file_sha256
from weather_basis.scenarios import build_global_season_plan, build_national

R04_CORRECTED_DIRECTORY = Path("results/v2/experiments/R04-v3-corrected")
R04_CORRECTED_PROTOCOL = Path("config/research/r04-common-scenarios.yaml")
PRODUCTION_ADAPTERS = {
    "r2j-raw-residual-before-ar-v1": {"r2j-common-horizon-production-bridged-v2"},
    "common-year-trend-bootstrap-v1": {"common-year-trend-bootstrap-v1"},
}


def _write(out: Path, name: str, value: dict) -> Path:
    path = out / name
    path.write_text(canonical_json(value) + "\n")
    return path


def _request_values(context, name: str) -> tuple:
    return tuple(context.request.get(name, ()))


def _file_records(directory: Path) -> dict[str, dict[str, object]]:
    """Hash every material file beneath a stage artifact directory."""
    return {
        str(path.relative_to(directory)): {
            "sha256": file_sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _corrected_r04(root: Path) -> tuple[Path, Path, dict, dict]:
    directory = root / R04_CORRECTED_DIRECTORY
    report_path = directory / "r04.json"
    choice_path = directory / "accepted-generator-selection.json"
    if not report_path.is_file() or not choice_path.is_file():
        raise FileNotFoundError("corrected R04-v3 report and accepted selection are required")
    report, choice = json.loads(report_path.read_text()), json.loads(choice_path.read_text())
    protocol = load_mapping(root / R04_CORRECTED_PROTOCOL)
    if report.get("experiment_id") != "R04-common-marginal-dependence-v3":
        raise ValueError("R04 report is not the corrected v3 protocol")
    if report.get("protocol_id") != content_id(protocol):
        raise ValueError("corrected R04 report does not match the frozen v3 protocol")
    if choice.get("report_id") != content_id(report):
        raise ValueError("corrected R04 selection does not match its report")
    if choice.get("selected_generator") != "r2j-raw-residual-before-ar-v1":
        raise ValueError("corrected R04 selection does not name the registered R2j generator")
    return report_path, choice_path, report, choice


def _validate_scenario_outputs(directory: Path, manifest: dict, scientific_generator: str) -> dict:
    """Reject non-finite chunks and record the production-adapter distinction."""
    scenario_set = manifest.get("scenario_set", {})
    adapter = scenario_set.get("generator_spec_id")
    if adapter not in PRODUCTION_ADAPTERS.get(scientific_generator, set()):
        raise ValueError(
            f"production adapter {adapter!r} is not registered for {scientific_generator!r}"
        )
    if scientific_generator == "r2j-raw-residual-before-ar-v1":
        if manifest.get("observation_cutoff") != "2026-05-31":
            raise ValueError("bridged R2j artifact must declare the May 31 2026 information cutoff")
        if manifest.get("bridge_days") != 30:
            raise ValueError("bridged R2j artifact must declare its shared June bridge")
        if scientific_generator not in set(scenario_set.get("model_spec_ids", ())):
            raise ValueError("bridged R2j artifact lost its selected scientific baseline")
    parent = scenario_set.get("scenario_set_id")
    declared = list(manifest.get("county_chunks", {}).values()) + [manifest.get("station_chunk")]
    if not parent or any(not name for name in declared):
        raise ValueError("scenario artifact lacks chunk parent or declared chunk files")
    checked: dict[str, list[int]] = {}
    for name in declared:
        path = directory / name
        with np.load(path, allow_pickle=False) as payload:
            required = {"values", "scenario_ids", "entity_ids", "parent_scenario_set_id", "units"}
            if not required <= set(payload.files):
                raise ValueError(f"scenario chunk {name} lacks standard matrix headers")
            if str(payload["parent_scenario_set_id"][0]) != parent:
                raise ValueError(f"scenario chunk {name} has a different ScenarioSet parent")
            values = payload["values"]
            if not np.all(np.isfinite(values)):
                raise ValueError(f"scenario chunk {name} contains non-finite values")
            checked[name] = list(values.shape)
    audit = directory / str(manifest.get("audit_daily_paths", ""))
    if not audit.is_file():
        raise FileNotFoundError("scenario artifact lacks audit daily paths")
    with np.load(audit, allow_pickle=False) as payload:
        if "values" not in payload or not np.all(np.isfinite(payload["values"])):
            raise ValueError("audit daily paths contain non-finite values")
        checked[str(audit.name)] = list(payload["values"].shape)
    return {
        "scientific_generator": scientific_generator,
        "production_adapter": adapter,
        "checked": checked,
    }


def _required_r2j_fit_parent(context) -> dict:
    candidates = [
        path / "fits.json"
        for path in context.dependency_directories.get("models.fit", [])
        if (path / "fits.json").is_file()
    ]
    if len(candidates) != 1:
        raise FileNotFoundError("R2j scenarios require exactly one models.fit/fits.json parent")
    parent = json.loads(candidates[0].read_text()).get("r2j_fit_parent")
    if not isinstance(parent, dict) or parent.get("kind") != "r2j-fit-parent":
        raise ValueError("models.fit artifact lacks a valid R2j fit parent")
    return parent


def handle_model_stage(stage, context, out):
    research = context.research
    if stage == "models.fit":
        if _request_values(context, "origins") or _request_values(context, "county_panel"):
            raise ValueError(
                "models.fit has no origin or county selector; use its global frozen plan"
            )
        plan = build_global_season_plan(
            context.root,
            offline_paths=int(research["offline_paths"]),
            valuation_asof=research["valuation_asof"],
            seed=int(research["seed"]),
            horizon_start=research["horizon_start"],
            horizon_end=research["horizon_end"],
        )
        fit_payload = {
            "global_plan_id": plan.plan_id,
            "source_hashes": plan.source_hashes,
            "eligible_seasons": plan.eligible_seasons,
            "cutoff": plan.cutoff,
        }
        if research["scenario_generator"] == "r2j-raw-residual-before-ar-v1":
            from weather_basis.scenarios.r2j_production import prepare_r2j_fit

            fit_payload["r2j_fit_parent"] = prepare_r2j_fit(
                context.root, valuation_asof=research["valuation_asof"], allow_fit=True
            )
        return [
            _write(
                out,
                "fits.json",
                fit_payload,
            )
        ]
    if stage == "tournament.execute":
        report_path, choice_path, report, choice = _corrected_r04(context.root)
        requested_origins = _request_values(context, "origins")
        reported_origins = tuple(row["origin"] for row in report["rows"])
        if requested_origins and requested_origins != reported_origins:
            raise ValueError("requested origins do not match the frozen corrected R04 protocol")
        if _request_values(context, "county_panel"):
            raise ValueError(
                "tournament.execute has a frozen representative panel; "
                "county selectors are rejected"
            )
        binding = {
            "schema_version": "2.0",
            "kind": "corrected-r04-v3-binding",
            "report": {
                "path": str(report_path),
                "sha256": file_sha256(report_path),
                "content_id": content_id(report),
            },
            "selection": {
                "path": str(choice_path),
                "sha256": file_sha256(choice_path),
                "content_id": content_id(choice),
            },
            "protocol": {
                "path": str(context.root / R04_CORRECTED_PROTOCOL),
                "sha256": file_sha256(context.root / R04_CORRECTED_PROTOCOL),
                "content_id": report["protocol_id"],
            },
            "experiment_id": report["experiment_id"],
            "origins": list(reported_origins),
            "selected_generator": choice["selected_generator"],
            "source_files": _file_records(report_path.parent),
        }
        return [_write(out, "r04-binding.json", binding)]
    if stage == "models.select":
        if _request_values(context, "origins") or _request_values(context, "county_panel"):
            raise ValueError("models.select has no origin or county selector")
        dependencies = [
            path / "r04-binding.json"
            for path in context.dependency_directories["tournament.execute"]
        ]
        bindings = [path for path in dependencies if path.is_file()]
        if len(bindings) != 1:
            raise FileNotFoundError("one corrected R04 binding is required for scenario selection")
        binding = json.loads(bindings[0].read_text())
        report_path = Path(binding["report"]["path"])
        choice_path = Path(binding["selection"]["path"])
        report, choice = json.loads(report_path.read_text()), json.loads(choice_path.read_text())
        if (
            content_id(report) != binding["report"]["content_id"]
            or content_id(choice) != binding["selection"]["content_id"]
        ):
            raise ValueError("corrected R04 binding no longer matches source evidence")
        selected = choice["selected_generator"]
        complete = [row for row in report["rows"] if row["status"] == "complete"]
        selection = {
            "generator_spec_id": selected,
            "disposition": choice.get("disposition"),
            "r04_report": str(report_path),
            "r04_report_id": content_id(report),
            "r04_selection": str(choice_path),
            "r04_selection_id": content_id(choice),
            "complete_origins": [row["origin"] for row in complete],
            "product_support": "daily/monthly only when supplied by the accepted generator",
            "source_files": _file_records(report_path.parent),
        }
        return [_write(out, "selection.json", selection)]
    raise ValueError(stage)


def handle_scenarios(context, out):
    if _request_values(context, "origins"):
        raise ValueError("scenarios.build does not accept origin selectors")
    selection = next(
        (
            path / "selection.json"
            for path in context.dependency_directories["models.select"]
            if (path / "selection.json").is_file()
        ),
        None,
    )
    if selection is None:
        raise FileNotFoundError("accepted model selection required")
    accepted = json.loads(selection.read_text())
    if accepted["generator_spec_id"] != context.research["scenario_generator"]:
        raise ValueError("research config and accepted selection disagree")
    county_ids = _request_values(context, "county_panel") or None
    mode = context.request["mode"]
    if mode == "full":
        if county_ids:
            raise ValueError("full scenario builds are national and reject county selectors")
        paths = int(context.research["offline_paths"])
    else:
        paths = int(context.research["public_paths"])
    scientific_generator = accepted["generator_spec_id"]
    if scientific_generator == "common-year-trend-bootstrap-v1":
        manifest = build_national(
            context.root, out / "chunks", context.research, county_ids=county_ids, paths=paths
        )
    elif scientific_generator == "r2j-raw-residual-before-ar-v1":
        from weather_basis.scenarios.r2j_production import build_r2j_production

        fit_parent = _required_r2j_fit_parent(context)
        manifest = build_r2j_production(
            context.root,
            out / "chunks",
            county_ids=county_ids,
            paths=paths,
            valuation_asof=context.research["valuation_asof"],
            seed=int(context.research["seed"]),
            fit_parent=fit_parent,
            allow_fit=False,
        )
        if manifest.get("fit_id") != fit_parent.get("fit_id"):
            raise ValueError("scenario artifact did not reuse the models.fit R2j parent")
    else:
        raise ValueError(f"no registered production adapter for {scientific_generator}")
    manifest["selection_report"] = str(selection)
    manifest["selection_report_sha256"] = file_sha256(selection)
    manifest["output_validation"] = _validate_scenario_outputs(
        out / "chunks", manifest, scientific_generator
    )
    manifest["output_files"] = _file_records(out / "chunks")
    _write(out, "scenarios.json", manifest)
    # Let the executor hash every county/station/audit byte, not merely this
    # JSON index, so a corrupted lazy chunk cannot be reused as a cache hit.
    return None
