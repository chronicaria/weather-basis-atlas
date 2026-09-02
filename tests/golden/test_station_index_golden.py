"""Plan Section 5.3: package station indexes reproduce independent GHCN excerpts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

pytestmark = pytest.mark.data
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/ghcnd_golden"
CASES = (
    ("USW00094846_2014-01.csv", "USW00094846", "HDD-01", 2014, "hdd"),
    ("USW00014922_2019-01.csv", "USW00014922", "HDD-01", 2019, "hdd"),
    ("USW00003927_2011-07.csv", "USW00003927", "CDD-07", 2011, "cdd"),
)


@pytest.mark.parametrize(("filename", "station", "pair", "season", "field"), CASES)
def test_station_monthly_index_matches_independent_reference(
    filename: str, station: str, pair: str, season: int, field: str
) -> None:
    """Plan Section 5.3: independent CSV arithmetic agrees with package output to 1e-9."""
    excerpt = FIXTURES / filename
    assert excerpt.is_file(), f"missing required golden excerpt: {excerpt}"
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tests/golden/independent_hdd.py"), str(excerpt)],
        capture_output=True,
        check=True,
        text=True,
    )
    expected = json.loads(completed.stdout)
    table = pd.read_parquet(ROOT / f"results/indices/station_{pair}.parquet")
    actual = table.loc[
        table["ghcnd_id"].eq(station) & table["season"].eq(season), "index"
    ]
    assert len(actual) == 1
    assert float(actual.iloc[0]) == pytest.approx(float(expected[field]), abs=1e-9)
