from pathlib import Path

import pytest

from weather_basis.application.public_release import _county_record, _matrix, _seasonal_structures


def test_public_projection_rejects_missing_or_unknown_county_fields():
    context = {
        "release_id": "candidate",
        "analysis_id": "analysis:test",
        "source_artifact_ids": ("artifact:test",),
        "data_vintage_id": "vintage:test",
        "model_spec_ids": (),
        "scenario_set_id": None,
        "valuation_asof": "2026-07-01",
        "evidence_reference": "test",
    }
    row = {
        "fips": "31109",
        "pair": "HDD-01",
        "historical_evidence": {},
        "current_availability": {},
        "selection_asof": {},
        "matched_policy": {},
    }
    with pytest.raises((KeyError, ValueError)):
        _county_record(
            row={k: v for k, v in row.items() if k != "matched_policy"},
            registry={"fips": "31109"},
            common=context,
        )
    with pytest.raises(ValueError):
        _county_record(row={**row, "unknown": True}, registry={"fips": "31109"}, common=context)


def test_public_projection_preserves_numeric_zero_and_separate_current_history():
    context = {
        "release_id": "candidate",
        "analysis_id": "analysis:test",
        "source_artifact_ids": ("artifact:test",),
        "data_vintage_id": "vintage:test",
        "model_spec_ids": (),
        "scenario_set_id": None,
        "valuation_asof": "2026-07-01",
        "evidence_reference": "test",
    }
    row = {
        "fips": "31109",
        "pair": "HDD-01",
        "historical_evidence": {"value": 0.0},
        "current_availability": {"value": 0.0},
        "selection_asof": {"station_id": "A"},
        "matched_policy": {"station_id": "B"},
    }
    record = _county_record(
        row=row, registry={"fips": "31109", "name": "Lancaster", "state": "NE"}, common=context
    )
    assert record.payload["historical_evidence"]["value"] == 0.0
    assert record.payload["current_availability"]["value"] == 0.0
    assert record.payload["selection_asof"]["station_id"] == "A"
    assert record.payload["matched_policy"]["station_id"] == "B"


def test_matrix_requires_exact_serialized_coordinates(tmp_path: Path):
    path = tmp_path / "bad.npz"
    import numpy as np

    np.savez(
        path,
        parent_scenario_set_id=np.array(["set"]),
        scenario_ids=np.array(["a"]),
        entity_ids=np.array(["x", "x"]),
        values=np.zeros((1, 2)),
        units=np.array(["degree_days"]),
    )
    with pytest.raises(ValueError, match="Duplicate"):
        _matrix(path)


def test_contract_structures_only_use_contiguous_public_horizon_members():
    hdd = _seasonal_structures("HDD-01")
    assert {item["aggregation"] for item in hdd} == {
        "option_on_strip",
        "sum_of_monthly_options",
    }
    assert hdd[0]["member_pair_ids"] == ["HDD-11", "HDD-12", "HDD-01", "HDD-02", "HDD-03"]
    assert hdd[0]["member_windows"][0]["start"] == "2026-11-01"
    assert hdd[0]["member_windows"][-1]["end"] == "2027-03-31"
    assert _seasonal_structures("CDD-09")[0]["member_pair_ids"] == [
        "CDD-07",
        "CDD-08",
        "CDD-09",
    ]
    assert _seasonal_structures("CDD-04") == []


def test_public_matrix_shares_only_identical_scenario_metadata(tmp_path: Path):
    import gzip
    import json

    from weather_basis.application.publishing import fixture_public_source
    from weather_basis.publishing.projections import write_public_data
    from weather_basis.schemas.public import ResultEnvelope

    source = json.loads(fixture_public_source(tmp_path / "source").read_text())
    objects = {key: ResultEnvelope.from_dict(value) for key, value in source["objects"].items()}
    from dataclasses import replace
    objects = {
        key: replace(value, source_artifact_ids=("artifact:one", "artifact:two"))
        for key, value in objects.items()
    }
    bootstrap = write_public_data(
        tmp_path / "public", bootstrap=source["bootstrap"], objects=objects
    )
    ref = bootstrap["objects"]["county_scenarios:31109"]
    wire = json.loads(gzip.decompress((tmp_path / "public" / ref["path"]).read_bytes()))
    original = source["objects"]["county_scenarios:31109"]
    assert "scenario_set" not in wire["payload"]
    assert (
        wire["payload"]["scenario_set_id"] == original["payload"]["scenario_set"]["scenario_set_id"]
    )
    import base64

    import numpy as np

    matrix = wire["payload"]["matrix"]
    assert matrix.pop("values_encoding") == "float32-le-base64"
    matrix["values"] = np.frombuffer(
        base64.b64decode(matrix.pop("values_bytes")), dtype="<f4"
    ).astype(float).reshape(matrix["shape"]).tolist()
    assert matrix == original["payload"]["matrix"]
    assert wire["object_id"] != original["object_id"]
    assert bootstrap["source_artifact_groups"][wire["source_artifact_ids"][0]] == [
        "artifact:one", "artifact:two"
    ]
    source["bootstrap"]["scenario_sets"][0]["support_policy"] = "different"
    with pytest.raises(ValueError, match="Shared ScenarioSet content mismatch"):
        write_public_data(tmp_path / "bad", bootstrap=source["bootstrap"], objects=objects)
