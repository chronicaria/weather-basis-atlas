"""Plan Section 10, Phase 0: bootstrap data, geography, and repository gate."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.data
ROOT = Path(__file__).resolve().parents[2]


def _json(path: str) -> dict:
    with (ROOT / path).open(encoding="utf-8") as handle:
        return json.load(handle)


def test_phase0_repository_commands_and_progress_log() -> None:
    """Plan Section 10 Phase 0: lint, ordinary tests, CLI help, and a progress entry pass."""
    for command in (["ruff", "check", "."], [sys.executable, "-m", "pytest"], ["wba", "--help"]):
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Phase 0" in (ROOT / "PROGRESS.md").read_text(encoding="utf-8")


def test_phase0_migrated_panel_and_geography() -> None:
    """Plan Section 10 Phase 0: the real TAVG panel and geography QC retain their fixed facts."""
    manifest = pd.read_csv(ROOT / "data/manifests/nclimgrid_tavg.csv")
    assert len(manifest) == 906
    verified = manifest.get("verified")
    assert verified is not None and verified.astype(bool).all()

    panel = np.load(ROOT / "data/panel/tavg_f32.npy", mmap_mode="r")
    assert panel.shape == (27_575, 3_107)
    assert not np.isnan(panel).any()
    assert panel.min() >= -60 and panel.max() <= 130

    geography = _json("results/qc/geography.json")
    assert geography["matched"] == 3_107
    assert set(map(str, geography["exceptions"])) == {"51678"}
    consistency = _json("results/qc/panel_consistency.json")
    assert consistency["max_deviation_f"] <= 0.036


def test_phase0_vendor_and_ci_contracts() -> None:
    """Plan Section 10 Phase 0: vendor provenance and parseable CI workflow are committed."""
    vendor = _json("web/vendor/VENDOR.json")
    assets = vendor.get("assets", vendor)
    # KaTeX ships separate executable and stylesheet assets, so the four
    # vendored libraries resolve to five hash-verified files.
    assert len(assets) == 5
    rows = assets.values() if isinstance(assets, dict) else assets
    assert all(isinstance(row, dict) and row.get("sha256") for row in rows)

    import yaml

    assert yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
