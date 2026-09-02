"""Plan Section 10, Phase 3: out-of-sample hedge-atlas gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from jsonschema import Draft202012Validator

from weather_basis.io import sha256

pytestmark = pytest.mark.data
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _require_phase2() -> None:
    required = ("results/indices/county_HDD-01.parquet", "docs/preregistration.md")
    missing = [path for path in required if not (ROOT / path).exists()]
    if missing:
        pytest.skip(f"Phase 3 requires completed Phase 2 artifacts: {', '.join(missing)}")


def test_phase3_atlas_dimensions_intervals_and_station_coverage() -> None:
    """Plan Section 10 Phase 3: dimensions, interval ordering, stability, and coverage hold."""
    pairs = pd.read_parquet(ROOT / "results/atlas/pairs.parquet")
    stations = pd.read_parquet(ROOT / "results/atlas/stations.parquet")
    assert len(pairs) == 43_498 and len(stations) == 565_474
    evaluable = pairs["n_test"] >= 1
    assert pairs.loc[evaluable, "he_pit"].notna().all()
    interval = pairs.dropna(subset=["he_pit_lb", "he_pit_ub"])
    assert (interval["he_pit_lb"] <= interval["he_pit_ub"]).all()
    enclosed = interval["he_pit"].between(interval["he_pit_lb"], interval["he_pit_ub"])
    assert enclosed.mean() >= 0.99
    assert pairs["stability"].dropna().between(0, 1).all()
    station_coverage = stations.groupby("station")["he_pooled"].apply(
        lambda series: series.notna().sum()
    )
    assert (station_coverage >= 1_000).all()


def test_phase3_headline_manifest_and_zero_distance() -> None:
    """Plan Sections 1, 10 Phase 3, and 13.3: headline, prereg hash, and provenance hold."""
    headline = json.loads((ROOT / "results/atlas/headline.json").read_text(encoding="utf-8"))
    pairs = headline.get("pairs", headline.get("results", []))
    assert len(pairs) == 14
    assert all("n_stations_effective" in row for row in pairs)
    assert len(pd.read_parquet(ROOT / "results/atlas/zero_distance.parquet")) == 13 * 14
    manifest = json.loads((ROOT / "results/manifests/atlas.json").read_text(encoding="utf-8"))
    prereg_hash = hashlib.sha256((ROOT / "docs/preregistration.md").read_bytes()).hexdigest()
    assert manifest["prereg_sha256"] == prereg_hash
    assert manifest["holdout_unlocked"] is False
    schema = json.loads((ROOT / "src/weather_basis/schemas/headline.schema.json").read_text())
    Draft202012Validator(schema).validate(headline)
    for relative, digest in manifest["sha256_out"].items():
        path = ROOT / relative
        assert path.is_file(), relative
        assert sha256(path) == digest, relative


def test_phase3_determinism_evidence_covers_every_committed_atlas_output() -> None:
    """Plan Sections 6.8 and 10 Phase 3: two identical atlas runs are attested byte-for-byte."""
    evidence = json.loads((ROOT / "results/qc/atlas_determinism.json").read_text(encoding="utf-8"))
    compared = evidence["hash_equality"]
    required = {
        "results/atlas/pairs.parquet", "results/atlas/stations.parquet",
        "results/atlas/bootstrap.parquet", "results/atlas/zero_distance.parquet",
        "results/atlas/headline.json",
    }
    assert required.issubset(compared)
    assert all(compared[name] is True for name in required)
