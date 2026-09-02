"""Plan Section 10, Phase 5: model-ladder and tournament gate."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from weather_basis.io import sha256

pytestmark = pytest.mark.data
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _require_phase4() -> None:
    required = ("site/data/meta.json", "results/atlas/pairs.parquet")
    missing = [path for path in required if not (ROOT / path).exists()]
    if missing:
        pytest.skip(f"Phase 5 requires completed Phase 4 artifacts: {', '.join(missing)}")


def test_phase5_tournament_calibration_and_joint_outputs() -> None:
    """Plan Section 10 Phase 5: selection, calibration, holdout, and joint diagnostics exist."""
    selection = pd.read_parquet(ROOT / "results/tournament/selection.parquet")
    assert {
        "pair", "state", "rung_selected", "skill", "skill_r1_r0", "skill_r2_r1",
        "lb_r1_r0", "ub_r1_r0", "lb_r2_r1", "ub_r2_r1", "n_origins",
    }.issubset(selection.columns)
    counties = pd.read_csv(ROOT / "data/metadata/counties.csv", dtype={"fips": str})
    expected_units = {
        (pair, state)
        for pair in _pairs()
        for state in counties["state_fips"].astype(str).str.zfill(2)
    }
    assert set(zip(selection["pair"], selection["state"], strict=True)) == expected_units
    calibration = pd.read_parquet(ROOT / "results/tournament/calibration.parquet")
    assert len(calibration) == 3_120
    assert calibration["mean_z2"].between(0.98, 1.02).all()
    assert calibration["diagnostic_basis"].eq("daily_R2_standardized_innovation").all()
    calibration_by_origin = pd.read_parquet(
        ROOT / "results/tournament/calibration_by_origin.parquet"
    )
    assert {"pair", "origin", "diagnostic_basis", "mean_z2"}.issubset(calibration_by_origin.columns)
    assert calibration_by_origin["diagnostic_basis"].eq("daily_R2_standardized_innovation").all()
    assert calibration_by_origin["mean_z2"].between(0.98, 1.02).all()
    joint = pd.read_parquet(ROOT / "results/tournament/joint_check.parquet")
    assert len(joint) == 18 * 14
    assert joint["r2j_beats_independent"].all()
    assert (joint["r2j_crps"] < joint["independent_r2_crps"]).all()
    holdout_path = ROOT / "results/tournament/holdout_check.json"
    holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
    assert holdout


def test_phase5_scores_power_and_model_manifest() -> None:
    """Plan Sections 10 Phase 5 and 13.3: scores, power statement, and manifest provenance exist."""
    config = yaml.safe_load((ROOT / "config/defaults.yaml").read_text(encoding="utf-8"))
    origins = range(config["tournament"]["origins"][0], config["tournament"]["origins"][1] + 1)
    expected_rows = 3_107 * len(origins)
    scores = sorted((ROOT / "results/tournament/scores").glob("*.parquet"))
    assert len(scores) == 14
    for path in scores:
        score = pd.read_parquet(path)
        assert set(score["rung"]) == {"R0", "R1", "R2"}
        assert score.groupby("rung").size().eq(expected_rows).all()
        assert score["origin"].nunique() == len(origins)
        assert score["fips"].nunique() == 3_107
    assert json.loads((ROOT / "results/tournament/power.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "results/manifests/tournament.json").read_text(encoding="utf-8"))
    assert manifest["holdout_unlocked"] is True
    for path in scores:
        relative = path.relative_to(ROOT).as_posix()
        assert manifest["sha256_out"].get(relative) == sha256(path)
    evidence = json.loads((ROOT / "results/tournament/determinism.json").read_text())
    assert evidence["engine"] == "daily_R2"
    assert evidence["hash_equality"] is True
    assert evidence["pair"] in _pairs() and int(evidence["origin"]) in origins


def _pairs() -> tuple[str, ...]:
    calendar = pd.read_csv(ROOT / "data/contracts/cme_contract_calendar.csv")
    return tuple(
        f"{row.index}-{int(row.month):02d}" for row in calendar.itertuples(index=False)
    )
