"""Plan Sections 12.2--12.3: fixture generation is NOAA-shaped and deterministic."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from weather_basis.config import load_config
from weather_basis.ingest.ghcnd import parse_station, qc_station
from weather_basis.validation.fixtures import FIXTURE_END, FIXTURE_START, generate_fixture


def _tree_hash(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_fixture_is_deterministic_and_has_the_required_coverage(tmp_path: Path) -> None:
    """Plan Sections 12.2--12.3: fixed-seed fixture bytes and donor coverage are stable."""

    first, second = tmp_path / "first", tmp_path / "second"
    first_paths, second_paths = generate_fixture(first), generate_fixture(second)
    assert _tree_hash(first) == _tree_hash(second)
    assert first_paths.counties.is_file() and second_paths.topojson.is_file()
    monthly = list((first / "raw" / "averages").rglob("tavg-*-cty-scaled.csv"))
    assert len(monthly) == 552
    counties = list(csv.DictReader(first_paths.counties.open(encoding="utf-8")))
    assert len(counties) == 20
    assert {"31109", "11001", "09001", "17031", "25025", "27053"}.issubset(
        {row["fips"] for row in counties}
    )
    assert len(first_paths.stations) == 3
    assert FIXTURE_START.isoformat() == "1951-01-01"
    assert FIXTURE_END.isoformat() == "1996-12-31"
    generate_fixture(tmp_path / "other-seed", seed=7)
    assert _tree_hash(first) != _tree_hash(tmp_path / "other-seed")


def test_fixture_noaa_and_ghcnd_shapes_exercise_sentinels_gaps_and_flags(tmp_path: Path) -> None:
    """Plan Sections 4.3, 4.5, and 12.2: generated source rows retain NOAA conventions."""

    paths = generate_fixture(tmp_path / "fixture")
    february = paths.raw / "averages" / "1951" / "tavg-195102-cty-scaled.csv"
    rows = list(csv.reader(february.open(encoding="utf-8", newline="")))
    assert len(rows) == 20 and all(len(row) == 37 for row in rows)
    assert rows[0][0] == "cty" and rows[0][5] == "TAVG" and rows[0][-1] == "-999.99"
    dc = next(row for row in rows if row[1] == "18511")
    assert dc[2].startswith("DC:")
    topology = json.loads(paths.topojson.read_text(encoding="utf-8"))
    assert len(topology["objects"]["counties"]["geometries"]) == 20
    assert all(item["type"] == "Polygon" for item in topology["objects"]["counties"]["geometries"])
    station = paths.stations[2].read_text(encoding="utf-8")
    assert "TMAX_ATTRIBUTES" in station and ",X,USW000" in station
    chicago = paths.stations[0].read_text(encoding="utf-8")
    assert "1970-06-10" in chicago and ",," in chicago
    chicago_qc = qc_station(parse_station(paths.stations[0]), load_config())
    june = chicago_qc.monthly.query("year == 1970 and month == 6").iloc[0]
    assert june["qc_status"] == "gap_filled" and june["n_gap_filled"] == 1
    boston_qc = qc_station(parse_station(paths.stations[2]), load_config())
    september = boston_qc.monthly.query("year == 1978 and month == 9").iloc[0]
    assert september["qc_status"] == "gap_filled" and september["n_missing"] == 1
