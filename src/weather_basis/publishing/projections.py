"""Public data is projected from identified scientific results, never V1 aliases."""

from __future__ import annotations

import base64
import gzip
import json
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from weather_basis.provenance.ids import canonical_json, content_id, file_sha256
from weather_basis.schemas.base import require, validate_fips, validate_json
from weather_basis.schemas.public import ResultEnvelope


def envelope(
    *,
    release_id: str,
    result_type: str,
    payload: dict[str, Any] | None,
    analysis_id: str,
    source_artifact_ids: tuple[str, ...],
    data_vintage_id: str,
    model_spec_ids: tuple[str, ...] = (),
    scenario_set_id: str | None = None,
    valuation_asof: str = "2026-07-01",
    index_definition_id: str = "temperature-dd-v2",
    units: str = "degree_days",
    currency: str | None = None,
    status: str = "available",
    reason_code: str | None = None,
    evidence_reference: str,
) -> ResultEnvelope:
    identity = {
        "result_type": result_type,
        "payload": payload,
        "analysis_id": analysis_id,
        "sources": source_artifact_ids,
        "scenario_set_id": scenario_set_id,
        "status": status,
        "reason_code": reason_code,
        "units": units,
        "currency": currency,
        "valuation_asof": valuation_asof,
        "index_definition_id": index_definition_id,
        "models": model_spec_ids,
    }
    return ResultEnvelope(
        release_id=release_id,
        object_id=content_id(identity, prefix="object"),
        result_type=result_type,
        analysis_id=analysis_id,
        source_artifact_ids=source_artifact_ids,
        data_vintage_id=data_vintage_id,
        model_spec_ids=model_spec_ids,
        scenario_set_id=scenario_set_id,
        valuation_asof=valuation_asof,
        index_definition_id=index_definition_id,
        units=units,
        currency=currency,
        payload=payload,
        status=status,
        reason_code=reason_code,
        evidence_reference=evidence_reference,
    )


def county_projection(
    *, row: dict[str, Any], registry: dict[str, Any], context: dict[str, Any]
) -> ResultEnvelope:
    validate_fips(row["fips"])
    require(row["fips"] == registry["fips"], "County identity mismatch")
    required = {
        "fips",
        "pair",
        "historical_evidence",
        "current_availability",
        "selection_asof",
        "matched_policy",
    }
    require(required <= set(row), f"Missing county projection fields {required - set(row)}")
    payload = {
        "county": registry,
        "index_definition": {"id": row["pair"], "label": row["pair"], "units": "degree_days"},
        **{key: row[key] for key in required - {"fips", "pair"}},
    }
    if "alternatives" in row:
        payload["alternatives"] = row["alternatives"]
    if "distribution" in row:
        payload["distribution"] = row["distribution"]
    return envelope(
        result_type="county_research", payload=payload, index_definition_id=row["pair"], **context
    )


def validate_bootstrap(data: dict[str, Any]) -> None:
    validate_json(data)
    required = {
        "schema_version",
        "release_id",
        "route_map",
        "county_registry",
        "index_definitions",
        "defaults",
        "objects",
        "scenario_sets",
        "capabilities",
    }
    require(required <= data.keys(), f"Missing bootstrap fields: {required - data.keys()}")
    require(data["schema_version"] == "2.0", "Unknown bootstrap schema")
    require(isinstance(data["release_id"], str) and bool(data["release_id"]), "Missing release")
    seen = set()
    for county in data["county_registry"]:
        fips = validate_fips(county["fips"])
        require(fips not in seen, "Duplicate county registry key")
        seen.add(fips)
    require(data["defaults"]["fips"] in seen, "Default county absent")
    for name, ref in {**data["objects"], **data.get("object_catalogs", {})}.items():
        require(isinstance(name, str) and isinstance(ref, dict), "Invalid object lookup")
        require(ref.get("release_id") == data["release_id"], "Mixed release reference")
        require(
            bool(ref.get("object_id") and ref.get("path") and ref.get("sha256")),
            "Incomplete public object reference",
        )
        path = Path(ref["path"])
        require(not path.is_absolute() and ".." not in path.parts, "Unsafe public object path")


def write_public_data(
    out: Path,
    *,
    bootstrap: dict[str, Any],
    objects: dict[str, ResultEnvelope] | Iterable[tuple[str, ResultEnvelope]],
    compress: bool = True,
) -> dict[str, Any]:
    """Write an isolated release data directory, verifying every reference and record."""
    require(not out.exists(), "Public release data destination must be fresh")
    out.mkdir(parents=True)
    (out / "objects").mkdir()
    lookup = {}
    seen = set()
    shared_sets = {item["scenario_set_id"]: item for item in bootstrap.get("scenario_sets", [])}
    contract_definitions = {}
    source_artifact_groups = {}
    iterator = sorted(objects.items()) if isinstance(objects, dict) else objects
    for key, record in iterator:
        validated = ResultEnvelope.from_dict(record.to_dict())
        require(validated.release_id == bootstrap["release_id"], "Mixed public object release")
        # A national DAG has dozens of pinned inputs. Their ordered provenance
        # is identical across records and resolves through one identified group.
        if len(validated.source_artifact_ids) > 1:
            sources = list(validated.source_artifact_ids)
            group_id = content_id(sources, prefix="source-group")
            source_artifact_groups[group_id] = sources
            validated = replace(
                validated,
                source_artifact_ids=(group_id,),
                object_id=content_id(
                    {"source_object_id": validated.object_id, "source_group": group_id},
                    prefix="object",
                ),
            )
        # Matrices keep every value and row ID. Resolve their common metadata
        # through the release bootstrap instead of shipping it 3,107 times.
        if validated.result_type == "scenario_matrix" and validated.payload:
            scenario_set = validated.payload.get("scenario_set")
            if scenario_set and scenario_set.get("scenario_set_id") in shared_sets:
                set_id = scenario_set["scenario_set_id"]
                require(scenario_set == shared_sets[set_id], "Shared ScenarioSet content mismatch")
                payload = {
                    key: value for key, value in validated.payload.items() if key != "scenario_set"
                }
                payload["scenario_set_id"] = set_id
                matrix = payload.get("matrix")
                if matrix and matrix.get("values") is not None:
                    values = np.asarray(matrix["values"], dtype=np.float64)
                    packed = values.astype("<f4")
                    # National production stores float32. Encode those exact
                    # bytes, while retaining float64 matrices as JSON if needed.
                    if np.array_equal(values, packed.astype(np.float64)):
                        payload["matrix"] = {
                            key: value for key, value in matrix.items() if key != "values"
                        }
                        payload["matrix"]["values_encoding"] = "float32-le-base64"
                        payload["matrix"]["values_bytes"] = base64.b64encode(
                            packed.tobytes(order="C")
                        ).decode("ascii")
                validated = replace(
                    validated,
                    payload=payload,
                    object_id=content_id(
                        {
                            "source_object_id": validated.object_id,
                            "projection": "shared-scenario-set-v1",
                            "payload": payload,
                        },
                        prefix="object",
                    ),
                )
        if validated.result_type == "contract_ticket" and validated.payload:
            ticket = validated.payload.get("option_contract")
            if isinstance(ticket, dict):
                shared = {
                    field: ticket[field]
                    for field in (
                        "contract_spec_id",
                        "currency",
                        "daily_window",
                        "selection_semantics",
                        "seasonal_structures",
                    )
                    if field in ticket
                }
                definition_id = content_id(shared, prefix="contract-definition")
                contract_definitions[definition_id] = shared
                payload = {
                    **validated.payload,
                    "contract_definition_id": definition_id,
                    "option_contract": {
                        field: value for field, value in ticket.items() if field not in shared
                    },
                }
                validated = replace(
                    validated,
                    payload=payload,
                    object_id=content_id(
                        {
                            "source_object_id": validated.object_id,
                            "projection": "shared-contract-definition-v1",
                            "payload": payload,
                        },
                        prefix="object",
                    ),
                )
        require(validated.object_id not in seen, "Duplicate object ID")
        seen.add(validated.object_id)
        # Object names are content IDs; validate the filename component as an extra boundary.
        filename = validated.object_id.replace(":", "-") + (".json.gz" if compress else ".json")
        require(Path(filename).name == filename, "Invalid public object ID")
        path = out / "objects" / filename
        raw = (canonical_json(validated.to_dict()) + "\n").encode()
        path.write_bytes(gzip.compress(raw, mtime=0) if compress else raw)
        lookup[key] = {
            "release_id": validated.release_id,
            "object_id": validated.object_id,
            "path": f"objects/{filename}",
            "sha256": file_sha256(path),
            "bytes": path.stat().st_size,
            "result_type": validated.result_type,
        }
    catalogs = {}
    if len(lookup) > 1000:
        partitions = {}
        for key in list(lookup):
            parts = key.split(":")
            if parts[0] in ("county", "county_scenarios", "quote") and len(parts) >= 2:
                group = f"{parts[0]}:{validate_fips(parts[1])[:2]}"
                partitions.setdefault(group, {})[key] = lookup.pop(key)
        (out / "catalogs").mkdir()
        for group, entries in sorted(partitions.items()):
            payload = {
                "schema_version": "2.0",
                "release_id": bootstrap["release_id"],
                "objects": entries,
            }
            object_id = content_id(payload, prefix="catalog")
            filename = object_id.replace(":", "-") + ".json.gz"
            path = out / "catalogs" / filename
            path.write_bytes(gzip.compress((canonical_json(payload) + "\n").encode(), mtime=0))
            catalogs[group] = {
                "release_id": bootstrap["release_id"],
                "object_id": object_id,
                "path": f"catalogs/{filename}",
                "sha256": file_sha256(path),
                "bytes": path.stat().st_size,
            }
    result = {
        **bootstrap,
        "objects": lookup,
        "object_catalogs": catalogs,
        "object_count": len(seen),
        "contract_definitions": contract_definitions,
        "source_artifact_groups": source_artifact_groups,
    }
    validate_bootstrap(result)
    (out / "bootstrap.json").write_text(canonical_json(result) + "\n")
    return result


def read_public_object(path: Path, *, release_id: str, expected_sha256: str) -> ResultEnvelope:
    require(file_sha256(path) == expected_sha256, "Public object content mismatch")
    raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    result = ResultEnvelope.from_dict(json.loads(raw))
    require(result.release_id == release_id, "Public object release mismatch")
    return result
