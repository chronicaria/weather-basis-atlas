"""Plan Section 10, Phase 6: quote engine and complete explorer gate."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd
import pytest

pytestmark = pytest.mark.data
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _require_phase5() -> None:
    required = ("results/tournament/selection.parquet", "results/tournament/joint_check.parquet")
    missing = [path for path in required if not (ROOT / path).exists()]
    if missing:
        pytest.skip(f"Phase 6 requires completed Phase 5 artifacts: {', '.join(missing)}")


def test_phase6_quote_coherence_nebraska_and_site() -> None:
    """Plan Sections 9.4 and 10 Phase 6: quote coherence, explorer smoke, and site checks pass."""
    coherence = json.loads((ROOT / "results/quotes/coherence.json").read_text(encoding="utf-8"))
    assert coherence.get("gate_violations", coherence.get("violations")) in (0, [])
    for path in (ROOT / "results/nebraska").glob("*.parquet"):
        assert len(pd.read_parquet(path)) == 18 * 14
    completed = subprocess.run(["wba", "site", "check"], cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    smoke = subprocess.run(
        ["pytest", "tests/site/test_smoke.py"], cwd=ROOT, capture_output=True, text=True
    )
    assert smoke.returncode == 0, smoke.stdout + smoke.stderr


def test_phase6_docs_and_payload_budget() -> None:
    """Plan Sections 9.2 and 10 Phase 6: metrics resolve and payloads meet their budget."""
    for path in (ROOT / "docs/site").glob("*.md"):
        assert "{{ metric(" not in path.read_text(encoding="utf-8")
    config_text = (ROOT / "config/defaults.yaml").read_text(encoding="utf-8")
    import yaml

    cap = yaml.safe_load(config_text)["site"]["county_payload_max_kb_gz"] * 1024
    payloads = list((ROOT / "site/data/county").glob("*.json.gz"))
    assert payloads and max(path.stat().st_size for path in payloads) <= cap
