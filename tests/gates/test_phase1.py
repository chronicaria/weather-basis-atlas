"""Plan Section 10, Phase 1: contract and station-data gate."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.data
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _require_phase0() -> None:
    """Skip only when the explicitly named prior Phase 0 artifacts are unavailable."""
    required = ("data/panel/tavg_f32.npy", "results/qc/geography.json")
    missing = [path for path in required if not (ROOT / path).exists()]
    if missing:
        pytest.skip(f"Phase 1 requires completed Phase 0 artifacts: {', '.join(missing)}")


def test_phase1_contract_universe_and_station_manifest() -> None:
    """Plan Section 10 Phase 1: contracts check and all 18 station snapshots are present."""
    completed = subprocess.run(
        ["wba", "contracts", "check"], cwd=ROOT, capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert len(pd.read_csv(ROOT / "data/contracts/cme_city_universe.csv")) == 13
    assert len(pd.read_csv(ROOT / "data/contracts/cme_contract_calendar.csv")) == 14
    assert len(pd.read_csv(ROOT / "data/contracts/cme_strips.csv")) == 8
    manifest = pd.read_csv(ROOT / "data/manifests/ghcnd_stations.csv")
    assert len(manifest) == 18
    assert manifest["sha256"].notna().all()


def test_phase1_station_panel_qc_and_counties() -> None:
    """Plan Section 10 Phase 1: station panel, QC rules, and geocoded county rows are fixed."""
    assert np.load(ROOT / "data/panel/stations_tbar_f32.npy", mmap_mode="r").shape == (27_575, 18)
    qc = json.loads((ROOT / "results/qc/stations.json").read_text(encoding="utf-8"))
    stations = qc.get("stations", qc)
    assert len(stations) == 18
    rows = stations.values() if isinstance(stations, dict) else stations
    # Some long station histories contain Celsius-native observations rather
    # than the overwhelmingly common integer-F round-trip grid. Preserve and
    # report that evidence; the current frozen vintage stays below ten percent.
    assert all(row["integer_f_deviation_flag_rate"] < 0.10 for row in rows)
    county = pd.read_csv(ROOT / "data/contracts/station_county.csv", dtype=str)
    assert len(county) == 18 and county["county_fips"].str.len().eq(5).all()


def test_phase1_station_indices_are_half_degree_multiples() -> None:
    """Plan Section 10 Phase 1: usable station indices remain on the half-degree grid."""
    for path in sorted((ROOT / "results/indices").glob("station_*.parquet")):
        values = pd.read_parquet(path)["index"].dropna().to_numpy()
        assert np.allclose(values * 2, np.rint(values * 2))
