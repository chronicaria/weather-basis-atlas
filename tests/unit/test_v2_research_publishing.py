# ruff: noqa: E501
import json
from pathlib import Path

import numpy as np

from weather_basis.portfolio import PortfolioProblem, optimize
from weather_basis.research.publishing import (
    compile_sample_books,
    decision_memo,
    decision_record,
    decisions_equal,
    export_decision,
    loss_on_matrix,
    research_envelopes,
    restore_decision,
    sample_book_envelopes,
)

ROOT = Path(__file__).parents[2]


def _record():
    solved = optimize(
        PortfolioProblem(
            losses=np.array([2.0, 10.0]), payoffs=np.array([[0.0], [10.0]]),
            scenario_ids=("a", "b"), candidate_ids=("station:USW00014939:HDD-01",),
        ),
        "es",
    )
    return decision_record(
        request={
            "holdings": [{"row_id": "x", "kind": "exposure", "entity_id": "county:31109:HDD-01",
                          "amount": 1.25, "units": "USD", "currency": "USD"}],
            "candidate_ids": ["station:USW00014939:HDD-01"],
        },
        result=solved,
        source_artifact_ids=("sha256:source",),
        scenario_set_id="scenario:test",
        question="Does this hedge reduce the illustrative loss?",
        uncertainty="Two equally weighted paths.",
        adverse_scenarios=["b"],
        maintenance_command="uv run wba v2 run --request request.json",
    )


def test_books_and_research_are_source_projected_with_explicit_partial_status():
    books = sample_book_envelopes(ROOT, release_id="release:test")
    assert set(books) == {
        "regional-heating-v1",
        "multi-location-cooling-v1",
        "underwriter-capped-claim-v1",
    }
    assert all(item.status == "partial" and item.payload["holdings"] for item in books.values())
    research = research_envelopes(ROOT, release_id="release:test")
    assert set(research) == {"r02", "r03", "r05", "nebraska"}
    assert research["r05"].payload["registered_experiment"]["scope"].startswith("bounded national")


def test_decision_exports_restore_with_deep_equality_and_memo_values(tmp_path):
    record = _record()
    paths = export_decision(tmp_path, record)
    restored = restore_decision(paths["result"])
    assert decisions_equal(record, restored)
    assert "Deterministic cost" in decision_memo(restored)
    assert "uv run wba v2 run" in decision_memo(restored, html=True)
    assert paths["holdings"].read_text().startswith("row_id,kind,entity_id,amount,units,currency")


def test_sample_books_compile_against_supplied_b11_matrix(tmp_path):
    books = [json.loads(path.read_text()) for path in (ROOT / "config/books").glob("*.json")]
    stations = {"31055": "USW00014942", "31109": "USW00014939", "31079": "USW00014935", "31111": "USW00024023", "31157": "USW00024028"}
    entities = sorted({row["entity_id"] for book in books for row in book["holdings"]} | {f"{stations[row['fips']]}:{row['pair']}" for book in books for row in book["holdings"]})
    scenario = tmp_path / "b11"
    scenario.mkdir()
    values = np.arange(64 * len(entities), dtype=float).reshape(64, len(entities)) % 400 + 900
    np.savez_compressed(scenario / "monthly.npz", values=values, scenario_ids=np.asarray([f"s{i}" for i in range(64)]), entity_ids=np.asarray(entities))
    (scenario / "manifest.json").write_text(json.dumps({"kind": "bounded-common-scenario-artifact", "artifact_id": "fixture:b11", "production_status": "artificial_fixture", "scenario_set": {"scenario_set_id": "fixture:set"}, "monthly_matrix": {"file": "monthly.npz"}}))
    compiled = compile_sample_books(ROOT, scenario, tmp_path / "out")
    assert set(compiled) == {
        "regional-heating-v1",
        "multi-location-cooling-v1",
        "underwriter-capped-claim-v1",
    }
    assert all(
        result["status"] == "available" and result["scenario_count"] == 64
        for result in compiled.values()
    )
    assert "incremental_claim" in compiled["underwriter-capped-claim-v1"]


def test_contract_claim_dsl_distinguishes_strip_monthly_and_collar():
    values = np.asarray([[8.0, 14.0], [12.0, 20.0]])
    columns = {"a:HDD-01": 0, "b:HDD-01": 1}
    base = {"kind": "claim", "loss_kind": "contract_payoff", "entity_id": "a:HDD-01", "member_entity_ids": ["a:HDD-01", "b:HDD-01"], "direction": 1, "payoff_spec": {"kind": "call", "strike": 15.0, "multiplier": 2.0}}
    assert np.allclose(loss_on_matrix({**base, "payoff_structure": "sum_of_monthly_options"}, values, columns), [0, 10])
    assert np.allclose(loss_on_matrix({**base, "payoff_structure": "option_on_strip"}, values, columns), [14, 34])
    collar = {**base, "member_entity_ids": ["a:HDD-01"], "payoff_structure": "monthly_option", "payoff_spec": {"kind": "collar", "strike": 10.0, "call_strike": 15.0, "multiplier": 2.0}}
    assert np.allclose(loss_on_matrix(collar, values, columns), [4, 0])
