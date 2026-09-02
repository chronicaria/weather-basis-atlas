"""Plan Section 10, Phase 2: preregistration and index-panel gate."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest
import yaml

pytestmark = pytest.mark.data
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _require_phase1() -> None:
    required = ("data/panel/stations_tbar_f32.npy", "data/manifests/ghcnd_stations.csv")
    missing = [path for path in required if not (ROOT / path).exists()]
    if missing:
        pytest.skip(f"Phase 2 requires completed Phase 1 artifacts: {', '.join(missing)}")


def test_phase2_preregistration_hash_is_locked() -> None:
    """Plan Sections 1 and 10 Phase 2: the committed preregistration hash matches configuration."""
    preregistration = ROOT / "docs/preregistration.md"
    digest = hashlib.sha256(preregistration.read_bytes()).hexdigest()
    config = yaml.safe_load((ROOT / "config/defaults.yaml").read_text(encoding="utf-8"))
    assert config["prereg"]["sha256"] == digest


def test_phase2_county_hdd_january_panel_is_complete() -> None:
    """Plan Section 10 Phase 2: county HDD-01 has all 3,107 series across 1951--2026."""
    panel = pd.read_parquet(ROOT / "results/indices/county_HDD-01.parquet")
    assert len(panel) == 3_107 * 76
    assert panel["season"].min() == 1951 and panel["season"].max() == 2026
    assert panel["index"].notna().all()


def test_phase2_station_missingness_matches_qc_status() -> None:
    """Plan Section 10 Phase 2: only excluded, provisional, and pre-start rows have NaN indices."""
    qc = pd.read_parquet(ROOT / "data/panel/station_qc.parquet")
    monthly = [
        path
        for path in sorted((ROOT / "results/indices").glob("station_*.parquet"))
        if path.stem.rsplit("-", 1)[1].isdigit()
    ]
    for path in monthly:
        panel = pd.read_parquet(path)
        month = int(path.stem.rsplit("-", 1)[1])
        month_qc = qc.loc[qc["month"] == month].rename(columns={"year": "season"})
        merged = panel.merge(
            month_qc[["ghcnd_id", "season", "qc_status"]],
            on=["ghcnd_id", "season"],
            how="left",
        )
        expected_nan = merged["qc_status"].isin(("excluded", "provisional", "pre_start"))
        assert (merged["index"].isna() == expected_nan).all()


def test_phase2_anomaly_counts_obey_registered_minimum_prior_rules() -> None:
    """Plan Sections 6.2 and 10 Phase 2: anomaly availability follows 15/10-prior rules."""
    for path in sorted((ROOT / "results/indices").glob("county_*.parquet")):
        frame = pd.read_parquet(path, columns=["fips", "anomaly", "n_prior"])
        assert frame["anomaly"].notna().equals(frame["n_prior"].ge(15))
        assert frame.groupby("fips", sort=False)["n_prior"].max().ge(15).all()
    for path in sorted((ROOT / "results/indices").glob("station_*.parquet")):
        frame = pd.read_parquet(path, columns=["anomaly", "n_prior", "index"])
        usable = frame["index"].notna()
        assert (frame.loc[usable, "anomaly"].notna() == frame.loc[usable, "n_prior"].ge(10)).all()
