"""Plan Section 10, Phase 4: static atlas-site gate."""

from __future__ import annotations

import filecmp
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.data
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _require_phase3() -> None:
    required = ("results/atlas/pairs.parquet", "results/atlas/headline.json")
    missing = [path for path in required if not (ROOT / path).exists()]
    if missing:
        pytest.skip(f"Phase 4 requires completed Phase 3 artifacts: {', '.join(missing)}")


def test_phase4_site_check_and_payload_inventory() -> None:
    """Plan Sections 9.4 and 10 Phase 4: site and browser smoke checks pass."""
    completed = subprocess.run(["wba", "site", "check"], cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    smoke = subprocess.run(
        ["pytest", "tests/site/test_smoke.py"], cwd=ROOT, capture_output=True, text=True
    )
    assert smoke.returncode == 0, smoke.stdout + smoke.stderr
    assert len(list((ROOT / "site/data/summary").glob("*.json"))) == 14
    assert len(list((ROOT / "site/data/county").glob("*.json.gz"))) == 3_107


def test_phase4_temp_rebuild_is_byte_stable(tmp_path: Path) -> None:
    """Plan Sections 9.4 and 12.3: a temporary rebuild equals the committed site byte-for-byte."""
    out = tmp_path / "site"
    completed = subprocess.run(
        ["wba", "site", "build", "--out", str(out)], cwd=ROOT, capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    comparison = filecmp.dircmp(ROOT / "site", out)
    assert not comparison.left_only and not comparison.right_only and not comparison.diff_files
