"""Unit coverage for plan sections 4.6, 4.7, and D-21 confidence proxies."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from weather_basis.ingest.confidence import (
    assess_confidence,
    haversine_km,
    station_density_by_decade,
    variance_regime_ratio,
)


def _inventory() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for element in ("TMAX", "TMIN"):
        rows.append(
            {
                "ghcnd_id": "US000000001",
                "lat": 40.0,
                "lon": -100.0,
                "element": element,
                "first_year": 1950,
                "last_year": 2025,
            }
        )
    rows.append(
        {
            "ghcnd_id": "US000000002",
            "lat": 40.0,
            "lon": -100.1,
            "element": "TMAX",
            "first_year": 1950,
            "last_year": 2025,
        }
    )
    return pd.DataFrame(rows)


def test_haversine_and_density_require_both_daily_temperature_elements() -> None:
    """D-21: density uses nearby stations with complete daily-temperature elements."""

    assert haversine_km(0.0, 0.0, 0.0, 1.0) == pytest.approx(111.195, rel=1e-5)
    counties = pd.DataFrame(
        {"fips": ["31001", "31003"], "lat": [40.0, 42.0], "lon": [-100.0, -100.0]}
    )
    density = station_density_by_decade(counties, _inventory(), decades=[2000])
    assert density["stations_within_30mi_2000"].tolist() == [1, 0]


def test_variance_ratio_demeans_each_year_and_marks_missing_windows() -> None:
    """D-21: variance regime comparisons avoid warming-level contamination."""

    dates = np.array(
        ["1951-01-01", "1951-01-02", "2001-01-01", "2001-01-02"], dtype="datetime64[D]"
    )
    values = np.array([[0.0, 1.0], [2.0, 3.0], [10.0, 1.0], [14.0, 3.0]])
    ratio = variance_regime_ratio(values, dates, early=(1951, 1951), late=(2001, 2001))
    assert np.allclose(ratio, [4.0, 1.0])
    assert np.isnan(
        variance_regime_ratio(values, dates, early=(1960, 1961), late=(2001, 2001))
    ).all()


def test_assess_confidence_is_data_only_and_uses_not_assessed() -> None:
    """Sections 4.6 and 13: flags are computed proxy values, never fit statistics."""

    counties = pd.DataFrame(
        {"fips": ["31001", "31003"], "lat": [40.0, 42.0], "lon": [-100.0, -100.0]}
    )
    dates = np.array(
        ["1951-01-01", "1951-01-02", "2001-01-01", "2001-01-02"], dtype="datetime64[D]"
    )
    values = np.array([[0.0, np.nan], [2.0, np.nan], [10.0, np.nan], [14.0, np.nan]])
    report = assess_confidence(counties, _inventory(), values, dates, decades=[2000])
    assert report.frame["confidence"].tolist() == ["low", "not_assessed"]
