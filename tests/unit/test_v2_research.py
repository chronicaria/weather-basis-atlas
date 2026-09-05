from pathlib import Path

from weather_basis.research.next_station import (
    adjudicate,
    freeze_choice,
    load_protocol,
    score_frozen_choice,
    summarize_pilot_rows,
)
from weather_basis.research.run import NEBRASKA, _bootstrap_mean


def test_research_protocol_has_all_required_experiments():
    text = (Path(__file__).parents[2] / "config/research/experiments-v2.yaml").read_text()
    assert all(item in text for item in ("R02:", "R03:", "R05:", "equivalence_bands"))


def test_nebraska_has_five_explicit_county_station_mappings():
    assert len(NEBRASKA) == 5
    assert {fips for fips, _ in NEBRASKA.values()} == {"31055", "31109", "31079", "31111", "31157"}


def test_paired_origin_bootstrap_refuses_one_origin():
    assert _bootstrap_mean(__import__("numpy").array([1.0])) == [None, None]


def test_next_station_choice_does_not_accept_a_heldout_outcome_and_missing_is_not_replaced():
    import numpy as np

    root = Path(__file__).parents[2]
    protocol = load_protocol(root)
    station_ids = protocol["baseline"]["station_ids"][:2]
    choice = freeze_choice(
        np.array([100.0, 80.0, 120.0, 70.0]),
        np.array([[50.0, 60.0], [45.0, 65.0], [40.0, 55.0], [60.0, 70.0]]),
        station_ids,
        objective="variance",
        protocol=protocol,
    )
    assert choice["candidate_ids"] == station_ids
    score = score_frozen_choice(
        choice, heldout_loss=90.0, heldout_indexes=np.array([np.nan, 50.0]), protocol=protocol
    )
    assert score == {"status": "unscoreable_missing_heldout_outcome", "residual_loss": None}


def test_next_station_writer_pairs_origins_and_uses_registered_adjudication():
    protocol = load_protocol(Path(__file__).parents[2])
    rows = []
    for objective in ("variance", "es"):
        for origin in range(2010, 2020):
            rows.extend(
                [
                    {
                        "origin": origin,
                        "objective": objective,
                        "sensitivity": "base",
                        "strategy": "baseline",
                        "status": "scored",
                        "residual_loss": 100.0 + 10.0 * (origin - 2010),
                        "deterministic_cost": 20.0,
                    },
                    {
                        "origin": origin,
                        "objective": objective,
                        "sensitivity": "base",
                        "strategy": "training_selected_one_addition",
                        "selected_addition": "USW00014942",
                        "status": "scored",
                        "residual_loss": 50.0 + 2.0 * (origin - 2010),
                        "deterministic_cost": 40.0,
                    },
                ]
            )
    summary = summarize_pilot_rows(rows, protocol)
    selected = [
        item
        for item in summary["objective_summary"]
        if item["strategy"] == "training_selected_one_addition" and item["sensitivity"] == "base"
    ]
    assert {item["paired_gain"]["paired_origins"] for item in selected} == {10}
    assert adjudicate(summary, protocol) == "promote"
