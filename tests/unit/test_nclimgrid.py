"""Unit coverage for plan Sections 4.3--4.4 nClimGrid parsing and provenance."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from weather_basis.ingest.nclimgrid import Month, NClimGridError, parse_month, source_url


def _row(code: str, label: str, values: list[str]) -> list[str]:
    return ["cty", code, label, "2023", "01", "TAVG", *values, *(["-999.99"] * (31 - len(values)))]


def test_parse_month_maps_crosswalk_dc_and_missing_values(tmp_path: Path) -> None:
    """Section 4.3: parser enforces format, converts the DC exception, and preserves NaN."""
    source = tmp_path / "tavg-202301-cty-scaled.csv"
    with source.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(
            [
                _row("04001", "CA:Alameda", ["10.0", "-999.99"]),
                _row("18511", "MD:District of Columbia", ["11.0", "12.0"]),
                _row("04013", "CA:Contra Costa", ["13.0", "14.0"]),
            ]
        )

    values, counties = parse_month(source, "tavg", Month(2023, 1), {"04": "06", "18": "24"})

    assert values.shape == (31, 3)
    assert [county.fips for county in counties] == ["06001", "06013", "11001"]
    assert counties[-1].state_fips == "11"
    assert counties[-1].name == "District of Columbia"
    assert np.isnan(values[1, 0])
    assert values[0].tolist() == [10.0, 13.0, 11.0]


def test_parse_month_rejects_wrong_column_count(tmp_path: Path) -> None:
    """Section 4.3: every raw NOAA row has exactly 37 columns."""
    source = tmp_path / "broken.csv"
    source.write_text("cty,04001,CA:Alameda,2023,01,TAVG\n", encoding="utf-8")
    with pytest.raises(NClimGridError, match="columns"):
        parse_month(source, "tavg", Month(2023, 1), {"04": "06"})


def test_source_url_is_pinned_to_noaa_county_pattern() -> None:
    """Section 4.4: endpoint names encode variable, compact month, county region and status."""
    assert source_url("tmin", Month(2026, 6)) == (
        "https://www.ncei.noaa.gov/data/nclimgrid-daily/access/averages/2026/"
        "tmin-202606-cty-scaled.csv"
    )
    assert Month(2023, 1).previous() == Month(2022, 12)
    assert Month(2023, 12).next() == Month(2024, 1)
