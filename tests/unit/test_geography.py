"""Unit coverage for plan section 4.7 geography and county reconciliation."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from weather_basis.http import FetchResult
from weather_basis.ingest.geography import (
    GeographyError,
    geocode_station,
    load_gazetteer,
    load_population,
    reconcile_fips,
)


def test_load_gazetteer_zip_normalizes_and_sorts(tmp_path: Path) -> None:
    """Section 4.7: names and centroids come from the 2020 Gazetteer."""

    source = tmp_path / "gazetteer.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "2020_Gaz_counties_national.txt",
            "GEOID\tNAME\tINTPTLAT\tINTPTLONG\n31009\tBlaine\t42.5\t-99.5\n01001\tAutauga\t32.5\t-86.5\n",
        )
    actual = load_gazetteer(source)
    assert actual.to_dict("records") == [
        {"fips": "01001", "name": "Autauga", "lat": 32.5, "lon": -86.5},
        {"fips": "31009", "name": "Blaine", "lat": 42.5, "lon": -99.5},
    ]


def test_population_excludes_state_totals_and_builds_fips(tmp_path: Path) -> None:
    """Section 4.7: population is keyed by county, including normal FIPS padding."""

    source = tmp_path / "population.csv"
    source.write_text("STATE,COUNTY,POPESTIMATE2020\n1,0,500\n1,1,10\n11,1,20\n")
    actual = load_population(source)
    assert actual.to_dict("records") == [
        {"fips": "01001", "pop2020": 10},
        {"fips": "11001", "pop2020": 20},
    ]


def test_reconcile_fips_requires_explicit_lexington_exception() -> None:
    """Section 4.7: the only permitted CONUS map-only ID is Lexington city."""

    report = reconcile_fips(
        {"01001", "11001"},
        {"01001", "11001", "51678", "02013"},
        pd.DataFrame({"fips": ["51678"]}),
    )
    assert report.matched == 2
    assert report.ok
    assert report.exceptions_applied == frozenset({"51678"})
    bad = reconcile_fips({"01001"}, {"01001", "51001"}, pd.DataFrame({"fips": ["51678"]}))
    assert bad.atlas_only == frozenset({"51001"})
    assert not bad.ok


def test_geocode_station_returns_raw_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """Section 4.7: geocoding preserves the exact Census response bytes."""

    raw = json.dumps({"result": {"geographies": {"Counties": [{"GEOID": "17031"}]}}}).encode()

    def fake_fetch(_url: str, path: Path, **_kwargs: object) -> FetchResult:
        path.write_bytes(raw)
        return FetchResult(path, "https://example.test", len(raw), "hash", None, None, "now", False)

    monkeypatch.setattr("weather_basis.ingest.geography.fetch", fake_fetch)
    assert geocode_station(41.98, -87.9) == ("17031", raw)
    with pytest.raises(GeographyError):
        geocode_station(100, 0)
