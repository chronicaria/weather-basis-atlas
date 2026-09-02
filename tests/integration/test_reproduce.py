"""Plan Sections 10 Phase 7 and 12.1--12.3: fixture reproduction is deterministic end to end."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def _run_fixture(out: Path) -> None:
    completed = subprocess.run(
        ["wba", "reproduce", "--fixture", "--out", str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_fixture_reproduce_is_complete_and_byte_stable(tmp_path: Path) -> None:
    """Plan Section 12.1: two fixture reproductions have usable OOS values and identical outputs."""
    first, second = tmp_path / "first", tmp_path / "second"
    _run_fixture(first)
    _run_fixture(second)
    first_pairs = pd.read_parquet(first / "results/atlas/pairs.parquet")
    second_pairs = pd.read_parquet(second / "results/atlas/pairs.parquet")
    assert (first_pairs["n_test"] >= 10).all()
    assert first_pairs["he_pit"].notna().all()
    assert first_pairs.equals(second_pairs)
    required_outputs = (
        "results/atlas/headline.json",
        "results/atlas/pairs.parquet",
        "results/quotes/quotes.parquet",
    )
    for relative in required_outputs:
        assert (first / relative).read_bytes() == (second / relative).read_bytes()
