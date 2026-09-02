"""Plan Section 10, Phase 5: model-ladder and tournament gate."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

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
    assert {"pair", "state", "skill"}.issubset(selection.columns)
    calibration = pd.read_parquet(ROOT / "results/tournament/calibration.parquet")
    assert len(calibration) == 3_120
    assert calibration["mean_z2"].between(0.98, 1.02).all()
    assert (ROOT / "results/tournament/calibration_by_origin.parquet").exists()
    joint = pd.read_parquet(ROOT / "results/tournament/joint_check.parquet")
    assert len(joint) == 18 * 14
    # Decision 0004 retains the row-level 2025 exceptions instead of changing
    # the data until every comparison is favorable. Joint alignment must win
    # in aggregate and for at least 90% of the registered diagnostics.
    assert joint["r2j_beats_independent"].mean() >= 0.90
    assert joint["r2j_crps"].mean() < joint["independent_r2_crps"].mean()
    holdout_path = ROOT / "results/tournament/holdout_check.json"
    holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
    assert holdout


def test_phase5_scores_power_and_model_manifest() -> None:
    """Plan Sections 10 Phase 5 and 13.3: scores, power statement, and manifest provenance exist."""
    scores = sorted((ROOT / "results/tournament/scores").glob("*.parquet"))
    assert len(scores) == 14
    assert json.loads((ROOT / "results/tournament/power.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "results/manifests/tournament.json").read_text(encoding="utf-8"))
    assert manifest["holdout_unlocked"] is True
