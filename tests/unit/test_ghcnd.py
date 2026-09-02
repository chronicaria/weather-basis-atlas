"""Build-plan Section 4.5: GHCN integer-F conversion and station QC."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from weather_basis.ingest.ghcnd import parse_station, qc_station, to_integer_f


def _tenths_c(fahrenheit: np.ndarray) -> np.ndarray:
    return np.rint((fahrenheit - 32.0) * 5.0 / 9.0 * 10.0)


def _cfg(**station: object) -> SimpleNamespace:
    defaults = {
        "integer_f_tolerance": 0.10,
        "max_gap_days": 2,
        "max_missing_share": 0.20,
        "provisional_months": 0,
    }
    defaults.update(station)
    return SimpleNamespace(station=SimpleNamespace(**defaults))


def _station_frame(dates: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "tmax_tenths_c": _tenths_c(np.full(len(dates), 70.0)),
            "tmin_tenths_c": _tenths_c(np.full(len(dates), 41.0)),
            "tmax_qflag": "",
            "tmin_qflag": "",
            "tmax_sflag": "",
            "tmin_sflag": "",
        }
    )


def test_integer_f_round_trip_for_all_rulebook_temperatures() -> None:
    """Section 4.5: every integer F from -60 through 130 round-trips cleanly."""
    values = np.arange(-60, 131, dtype=float)
    converted, flagged = to_integer_f(_tenths_c(values), tolerance=0.10)
    np.testing.assert_array_equal(converted, values)
    assert not flagged.any()


def test_parse_station_keeps_quality_and_source_flags(tmp_path) -> None:
    """Section 4.5: parser reads only required GHCN fields and attribute positions."""
    source = tmp_path / "station.csv"
    source.write_text(
        "DATE,TMAX,TMAX_ATTRIBUTES,TMIN,TMIN_ATTRIBUTES,PRCP\n"
        "2014-01-01,100,,0,,12\n"
        "2014-01-02,111,,10,,0\n"
        "2014-01-03,122,,20,,0\n"
        "2014-01-04,133,,30,,0\n"
        '2014-01-05,144,,40,",X,",0\n'
        "2014-01-06,155,,,M,,0\n",
        encoding="utf-8",
    )
    parsed = parse_station(source)
    assert list(parsed.columns) == [
        "date",
        "tmax_tenths_c",
        "tmin_tenths_c",
        "tmax_qflag",
        "tmin_qflag",
        "tmax_sflag",
        "tmin_sflag",
    ]
    assert parsed.loc[4, "tmin_qflag"] == "X"
    assert parsed.loc[5, "tmax_sflag"] == ""


def test_qc_fills_two_day_gap_on_integer_components_and_excludes_longer_gap() -> None:
    """Section 4.5: only short interior gaps are interpolated and integer-rounded."""
    dates = pd.date_range("2014-01-01", "2014-02-28", freq="D")
    frame = _station_frame(dates)
    frame.loc[frame["date"].isin(pd.date_range("2014-01-10", "2014-01-11")), "tmax_tenths_c"] = (
        np.nan
    )
    frame.loc[frame["date"] == pd.Timestamp("2014-01-10"), "tmin_qflag"] = "X"
    frame.loc[frame["date"].isin(pd.date_range("2014-02-10", "2014-02-12")), "tmin_tenths_c"] = (
        np.nan
    )

    qc = qc_station(frame, _cfg())
    jan = qc.monthly.query("year == 2014 and month == 1").iloc[0]
    feb = qc.monthly.query("year == 2014 and month == 2").iloc[0]
    assert jan.qc_status == "gap_filled"
    assert jan.n_missing == 2
    assert jan.longest_gap == 2
    assert jan.n_gap_filled == 2
    assert feb.qc_status == "excluded"
    assert feb.longest_gap == 3
    jan_values = qc.daily.loc[qc.daily.date.dt.month == 1, "tbar_f"].dropna().to_numpy()
    assert np.allclose(jan_values * 2, np.rint(jan_values * 2))


def test_qc_marks_recent_complete_months_provisional() -> None:
    """Section 4.5: the final two complete months are not scoring-eligible."""
    frame = _station_frame(pd.date_range("2014-01-01", "2014-03-31", freq="D"))
    qc = qc_station(frame, _cfg(provisional_months=2))
    assert qc.monthly.qc_status.tolist() == ["complete", "provisional", "provisional"]


def test_qc_does_not_count_a_partial_final_month_as_provisional() -> None:
    """Section 4.5: only complete source months enter the real-time lag rule."""

    frame = _station_frame(pd.date_range("2014-01-01", "2014-03-15", freq="D"))
    qc = qc_station(frame, _cfg(provisional_months=2))
    assert qc.monthly.qc_status.tolist() == ["provisional", "provisional", "excluded"]


def test_qc_does_not_treat_a_partial_boundary_month_as_complete() -> None:
    """Section 4.5: QC computes coverage against the calendar-month day count."""
    frame = _station_frame(pd.date_range("2014-01-15", "2014-02-28", freq="D"))
    qc = qc_station(frame, _cfg())
    january = qc.monthly.query("year == 2014 and month == 1").iloc[0]
    assert january.n_days == 31
    assert january.n_missing == 14
    assert january.qc_status == "excluded"


def test_qc_excludes_an_unfillable_short_edge_gap() -> None:
    """A short run still excludes the month when no right endpoint exists."""
    frame = _station_frame(pd.date_range("1995-09-01", "1995-09-30", freq="D"))
    frame.loc[frame["date"] == pd.Timestamp("1995-09-30"), "tmin_tenths_c"] = np.nan
    september = qc_station(frame, _cfg()).monthly.iloc[0]
    assert september.n_missing == 1
    assert september.n_gap_filled == 0
    assert september.qc_status == "excluded"


def test_invalid_tolerance_is_rejected() -> None:
    """Section 4.5: conversion tolerance is a non-negative data-quality threshold."""
    with pytest.raises(ValueError, match="tolerance"):
        to_integer_f(np.array([100.0]), tolerance=-0.01)
