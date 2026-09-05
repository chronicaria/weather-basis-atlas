"""Projection adapters connecting numerical artifacts to the public workbench."""

from __future__ import annotations

import json
import platform
from pathlib import Path

import numpy as np

from weather_basis.provenance.ids import canonical_json, content_id, file_sha256
from weather_basis.publishing.projections import envelope
from weather_basis.schemas.base import require


def fixture_public_source(out: Path) -> Path:
    from weather_basis.application.fixtures import fixture_scenarios

    scenario_set, matrix = fixture_scenarios()
    counties = [
        {"fips": "31109", "name": "Lancaster County", "state": "NE"},
        {"fips": "17031", "name": "Cook County", "state": "IL"},
        {"fips": "13075", "name": "Cook County", "state": "GA"},
    ]
    common = dict(
        release_id="candidate",
        analysis_id=content_id({"fixture": "vertical-v1"}),
        source_artifact_ids=(content_id({"fixture": "weather-hand-example-v1"}),),
        data_vintage_id="artificial-fixture-v1",
        model_spec_ids=("hand-example",),
        scenario_set_id=scenario_set.scenario_set_id,
        evidence_reference="Artificial fixture; never empirical weather evidence",
    )
    objects = {}
    for county in counties:
        objects[f"county:{county['fips']}:HDD-01"] = envelope(
            result_type="county_research",
            payload={
                "county": county,
                "index_definition": {
                    "id": "HDD-01",
                    "label": "January HDD",
                    "units": "degree_days",
                },
                "historical_evidence": {
                    "status": "unavailable",
                    "reason_code": "artificial_fixture",
                },
                "current_availability": {
                    "status": "unavailable",
                    "reason_code": "artificial_fixture",
                },
                "selection_asof": None,
                "matched_policy": None,
                "scope": "Artificial fixture for numerical and browser checks",
            },
            **common,
        )
    objects["summary:HDD-01"] = envelope(
        result_type="national_summary",
        payload={
            "scope": "artificial_fixture",
            "rows": [
                {
                    "fips": c["fips"],
                    "layers": {
                        "effectiveness": {"value": None, "reason_code": "artificial_fixture"}
                    },
                }
                for c in counties
            ],
        },
        **common,
    )
    for county in counties[:2]:
        chunk = matrix.select(
            tuple(e for e in matrix.entity_ids if e.startswith(county["fips"] + ":"))
        )
        objects[f"county_scenarios:{county['fips']}"] = envelope(
            result_type="scenario_matrix",
            payload={"scenario_set": scenario_set.to_dict(), "matrix": chunk.to_dict()},
            **common,
        )
    stations = matrix.select(tuple(e for e in matrix.entity_ids if e.startswith("fixture-station")))
    objects["station_scenarios"] = envelope(
        result_type="scenario_matrix",
        payload={"scenario_set": scenario_set.to_dict(), "matrix": stations.to_dict()},
        **common,
    )
    for key, kind, county in (
        ("regional-heating-v1", "heating_shortfall", "31109"),
        ("multi-location-cooling-v1", "cooling_overrun", "17031"),
        ("underwriter-capped-claim-v1", "cooling_overrun", "31109"),
    ):
        objects[f"book:{key}"] = envelope(
            result_type="book",
            units="USD",
            currency="USD",
            payload={
                "book_id": key,
                "title": key.replace("-", " "),
                "scope": "artificial_fixture",
                "question": "Exercise the fixture ledger and browser solver.",
                "objective": "es",
                "scenario_set_id": scenario_set.scenario_set_id,
                "holdings": [
                    {
                        "row_id": "exposure-1",
                        "kind": "exposure",
                        "entity_id": f"{county}:HDD-01",
                        "loss_kind": kind,
                        "amount": 10.0 / 31,
                        "budget": 62.0,
                        "base": 62.0,
                        "units": "USD/degree_day",
                        "currency": "USD",
                    }
                ],
                "problem": {
                    "losses": [10.0, 20.0, 40.0],
                    "payoffs": [[0.0], [10.0], [30.0]],
                    "scenario_ids": list(scenario_set.scenario_ids),
                    "candidate_ids": ["fixture-station-A:HDD-01"],
                    "weights": list(scenario_set.probability_weights),
                    "unit_costs": [0.0],
                    "fixed_cost": 2.0,
                    "upper_bounds": [2.0],
                },
                "availability": {"status": "available", "reason_code": None},
            },
            **common,
        )
    objects["research:fixture"] = envelope(
        result_type="research",
        payload={
            "title": "Artificial numerical fixture",
            "summary": "No empirical research conclusion is represented.",
            "result": "The independent long hedge ledger is [12,12,12] with cost counted once.",
        },
        **common,
    )
    bootstrap = {
        "schema_version": "2.0",
        "release_id": "candidate",
        "route_map": {},
        "county_registry": counties,
        "index_definitions": [{"id": "HDD-01", "units": "degree_days"}],
        "defaults": {
            "fips": "31109",
            "index_id": "HDD-01",
            "valuation_asof": "2026-07-01",
            "contract_window": {"start": "2027-01-01", "end": "2027-01-31", "year": 2027},
            "payoff": {"family": "call", "strike": 62.0, "multiplier": 20.0},
        },
        "objects": {},
        "scenario_sets": [scenario_set.to_dict()],
        "capabilities": {
            "max_locations": 6,
            "max_exposure_rows": 24,
            "max_hedge_columns": 39,
            "max_horizon_months": 12,
            "public_paths": 3,
            "scope": "artificial_fixture",
        },
    }
    out.mkdir(parents=True, exist_ok=True)
    path = out / "public-source.json"
    path.write_text(
        canonical_json(
            {
                "bootstrap": bootstrap,
                "objects": {key: value.to_dict() for key, value in objects.items()},
            }
        )
        + "\n"
    )
    return path


def handle_publishing_stage(stage, context, out):
    if context.request["mode"] == "fixture":
        if stage in ("atlas.select_asof", "quotes.build"):
            from weather_basis.portfolio.payoffs import call, put

            x = np.array([5.0, 10.0, 15.0])
            data = {
                "scope": "artificial_fixture",
                "index": x.tolist(),
                "call": call(x, 10).tolist(),
                "put": put(x, 10).tolist(),
                "selection_asof": {"status": "unavailable", "reason_code": "artificial_fixture"},
            }
            p = out / "quote.json"
            p.write_text(canonical_json(data) + "\n")
            return [p]
        if stage == "cases.build":
            return [fixture_public_source(out)]
        if stage in ("site.build", "release.verify"):
            from weather_basis.publishing.release import build_release, verify_release

            if stage == "release.verify":
                folders = context.dependency_directories["site.build"]
                bundle = folders[0] / "bundle"
                result = verify_release(bundle)
                p = out / "verification.json"
                p.write_text(canonical_json(result) + "\n")
                return [p]
            source = context.dependency_directories["cases.build"][0] / "public-source.json"
            lock = make_release_lock(context.root, source, scope="artificial_fixture")
            lock_path = out / "fixture.lock.json"
            lock_path.write_text(canonical_json(lock) + "\n")
            build_release(context.root, lock_path, out / "bundle")
            return None
    if stage == "atlas.select_asof":
        from weather_basis.hedge.asof import current_pair

        ids = tuple(np.load(context.root / "data/panel/station_ids.npy").astype(str)[:13])
        for pair in context.request["pairs"] or context.research["pairs"]:
            data = current_pair(context.root, pair, modeled_station_ids=ids)
            (out / f"{pair}.json").write_text(canonical_json(data) + "\n")
        return None
    from weather_basis.application.public_release import handle_real_publishing

    return handle_real_publishing(stage, context, out)


def make_release_lock(root: Path, public_source: Path, *, scope: str, artifacts=None):
    from weather_basis.publishing.release import _tree_sha256

    require(
        public_source.is_relative_to(root),
        "Public source must be inside retained repository artifact store",
    )
    sources = {
        str(p.relative_to(root)): file_sha256(p)
        for folder in ("apps/site", "src/weather_basis/publishing")
        for p in sorted((root / folder).rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }
    sources["uv.lock"] = file_sha256(root / "uv.lock")
    for filename in (
        "d3.v7.9.0.min.js",
        "topojson-client.v3.1.0.min.js",
        "counties-albers-10m.json",
    ):
        vendor = root / "web/vendor" / filename
        if not vendor.is_file():
            vendor = root / "site/assets/vendor" / filename
        sources[str(vendor.relative_to(root))] = file_sha256(vendor)
    research_hashes = {
        str(path.relative_to(root)): file_sha256(path)
        for folder in ("config/research", "config/vintages", "config/contracts", "config/books")
        for path in sorted((root / folder).rglob("*"))
        if path.is_file()
    }
    source_path = str(public_source.relative_to(root))
    blueprint = json.loads(public_source.read_text())
    scenario_sets = blueprint.get("bootstrap", {}).get("scenario_sets", [])
    scientific_sources = {
        str(path.relative_to(root)): file_sha256(path)
        for path in sorted((root / "src/weather_basis").rglob("*.py"))
        if "__pycache__" not in path.parts
    }
    legacy = root / "var/archive/v1/site"
    require((legacy / "index.html").is_file(), "Preserve the V1 site before sealing a V2 release")
    return {
        "schema_version": "2.0",
        "research": {
            "scope": scope,
            "configuration_hashes": research_hashes,
            "source_hashes": scientific_sources,
            "scientific_config_id": content_id(research_hashes),
            "scenario_set_ids": [item["scenario_set_id"] for item in scenario_sets],
            "model_spec_ids": sorted(
                {model for item in scenario_sets for model in item.get("model_spec_ids", [])}
            ),
            "data_vintage_ids": sorted(
                {item["data_vintage_id"] for item in scenario_sets}
            ),
            "numerical_environment": {
                "python": platform.python_version(),
                "numpy": np.__version__,
                "dependency_lock_sha256": file_sha256(root / "uv.lock"),
            },
        },
        "presentation": {"base_path": "/weather-basis-atlas/", "source_hashes": sources},
        "public_source": {"path": source_path, "sha256": file_sha256(public_source)},
        "legacy_bundle": {"path": str(legacy.relative_to(root)), "sha256": _tree_sha256(legacy)},
        "artifacts": artifacts
        or [
            {
                "artifact_id": content_id(
                    {"path": source_path, "sha256": file_sha256(public_source)}
                ),
                "path": source_path,
                "sha256": file_sha256(public_source),
                "access_class": "public_release",
            }
        ],
        "route_map": {
            "/": "index.html",
            "/compare": "compare.html",
            "/contract": "contract.html",
            "/portfolio": "portfolio.html",
            "/research/": "research/index.html",
        },
    }
