"""Plan Sections 4.3, 4.5, 4.6, and 4.7: real frozen NOAA inputs retain fixed facts."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.data
ROOT = Path(__file__).resolve().parents[2]


def test_real_county_panel_fixed_facts() -> None:
    """Plan Section 4.3: daily county panel is complete and captures the February 2021 cold wave."""
    panel = np.load(ROOT / "data/panel/tavg_f32.npy", mmap_mode="r")
    dates = np.load(ROOT / "data/panel/dates.npy", mmap_mode="r")
    assert panel.shape == (27_575, 3_107)
    assert not np.isnan(panel).any()
    february_2021 = panel[
        (dates >= np.datetime64("2021-02-01")) & (dates < np.datetime64("2021-03-01"))
    ]
    assert -30 <= float(february_2021.min()) <= -20
    january_2023 = panel[
        (dates >= np.datetime64("2023-01-01")) & (dates < np.datetime64("2023-02-01"))
    ]
    assert january_2023.size == 96_317


def test_real_station_qc_and_geography_reports_are_complete() -> None:
    """Plan Sections 4.5--4.7: all station QC and geography evidence is persisted."""
    qc = pd.read_parquet(ROOT / "data/panel/station_qc.parquet")
    registry = pd.read_csv(ROOT / "data/metadata/station_registry.csv", dtype={"ghcnd_id": str})
    assert set(qc["ghcnd_id"]) == set(registry["ghcnd_id"])
    stations = json.loads((ROOT / "results/qc/stations.json").read_text())
    rows = stations.get("stations", stations)
    assert len(rows) == 18
    geography = json.loads((ROOT / "results/qc/geography.json").read_text())
    assert geography["matched"] == 3_107
    confidence = json.loads((ROOT / "results/qc/confidence.json").read_text())
    assert len(confidence.get("counties", confidence)) == 3_107
