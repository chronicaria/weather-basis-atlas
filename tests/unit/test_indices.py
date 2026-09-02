"""Tests for plan Sections 5.2, 5.3, and 6.2 index definitions."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from weather_basis.indices.anomalies import anomaly, prior_counts, trailing_normal
from weather_basis.indices.county import build_county_frame
from weather_basis.indices.county import monthly_indices as county_monthly_indices
from weather_basis.indices.seasons import seasons_for_pair
from weather_basis.indices.station import build_station_frame
from weather_basis.indices.station import monthly_indices as station_monthly_indices
from weather_basis.indices.strips import build_strip_frame


def test_county_january_hdd_matches_days_times_difference() -> None:
    """Plan Section 5.3: HDD is applied daily and summed over the calendar month."""
    dates = np.arange("2020-01-01", "2020-02-01", dtype="datetime64[D]")
    values = np.full((31, 2), [40.0, 50.0])
    seasons, index = county_monthly_indices(values, dates, ["HDD-01"])["HDD-01"]
    np.testing.assert_array_equal(seasons, [2020])
    np.testing.assert_allclose(index, [[31 * 25, 31 * 15]], atol=1e-12)


def test_calendar_year_labels_december_and_january() -> None:
    """Plan Section 5.2: a season is the calendar year of its contract month."""
    dates = np.array(["2020-12-31", "2021-01-01"], dtype="datetime64[D]")
    np.testing.assert_array_equal(seasons_for_pair(dates, "HDD-12"), [2020, -1])
    np.testing.assert_array_equal(seasons_for_pair(dates, "HDD-01"), [-1, 2021])


def test_normals_need_minimum_available_prior_seasons() -> None:
    """Plan Section 6.2: normal/anomaly is absent until the required history exists."""
    x = np.arange(20.0)[:, None]
    normal = trailing_normal(x, min_prior=15)
    assert np.isnan(normal[:15]).all()
    assert normal[15, 0] == pytest.approx(7.0)
    assert anomaly(x, min_prior=15)[15, 0] == pytest.approx(8.0)
    np.testing.assert_array_equal(prior_counts(x), np.minimum(np.arange(20), 30)[:, None])


def test_station_missing_and_qc_months_are_nan() -> None:
    """Plan Sections 4.5 and 6.1: excluded/provisional station months are unavailable."""
    dates = np.arange("2020-01-01", "2020-03-01", dtype="datetime64[D]")
    values = np.full((dates.size, 2), 40.0)
    values[0, 1] = np.nan
    qc = pd.DataFrame(
        {
            "ghcnd_id": ["A"],
            "year": [2020],
            "month": [2],
            "qc_status": ["provisional"],
        }
    )
    seasons, index = station_monthly_indices(
        values, dates, ["HDD-01", "HDD-02"], station_ids=["A", "B"], station_qc=qc
    )["HDD-01"]
    np.testing.assert_array_equal(seasons, [2020])
    assert index[0, 0] == pytest.approx(31 * 25)
    assert np.isnan(index[0, 1])
    february = station_monthly_indices(
        values, dates, ["HDD-02"], station_ids=["A", "B"], station_qc=qc
    )["HDD-02"][1]
    assert np.isnan(february[0, 0])
    assert february[0, 1] == pytest.approx(29 * 25)


def test_county_frame_has_canonical_long_columns() -> None:
    """Plan Section 6.1: county result rows carry index, normal, anomaly, and history count."""
    dates = np.arange("2000-01-01", "2017-02-01", dtype="datetime64[D]")
    values = np.full((dates.size, 1), 40.0)
    frame = build_county_frame(values, dates, ["00001"], "HDD-01")
    assert list(frame.columns) == [
        "pair",
        "fips",
        "season",
        "index",
        "normal",
        "anomaly",
        "n_prior",
    ]
    assert frame.loc[frame.season == 2015, "normal"].iloc[0] == pytest.approx(775.0)


def test_station_frame_accepts_one_pass_identifier_iterable() -> None:
    """Plan Section 6.1: the long station result preserves every station identifier."""
    dates = np.arange("2000-01-01", "2011-02-01", dtype="datetime64[D]")
    values = np.full((dates.size, 1), 40.0)
    frame = build_station_frame(values, dates, (x for x in ["USW00000001"]), "HDD-01")
    assert frame.ghcnd_id.unique().tolist() == ["USW00000001"]


def test_hdd_november_to_march_strip_uses_prior_year_components() -> None:
    """Plan Section 5.2: Nov--Mar HDD strips are labelled by the March year."""
    def component(key: str, seasons: list[int], value: float) -> pd.DataFrame:
        return pd.DataFrame(
            {"pair": key, "fips": ["00001"] * len(seasons), "season": seasons, "index": value}
        )

    strip = build_strip_frame(
        (
            (component("HDD-11", [2019, 2020], 1), -1),
            (component("HDD-12", [2019, 2020], 2), -1),
            (component("HDD-01", [2020, 2021], 3), 0),
            (component("HDD-02", [2020, 2021], 4), 0),
            (component("HDD-03", [2020, 2021], 5), 0),
        ),
        strip="HDD-X",
        identifier_name="fips",
        window=30,
        min_prior=1,
    )
    assert strip.season.tolist() == [2020, 2021]
    assert strip["index"].tolist() == [15, 15]
