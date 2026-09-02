"""Contract tests enforcing plan Sections 5.2, 5.3, and decision D-32/D-33."""

from datetime import date

import numpy as np
import pytest

from weather_basis.contracts.calendar import (
    PAIRS,
    STRIPS,
    Pair,
    as_of,
    fit_through,
    season_of,
    settlement_date,
)
from weather_basis.contracts.degree_days import daily_cdd, daily_hdd, monthly_index
from weather_basis.contracts.payoff import call, futures, put
from weather_basis.contracts.universe import load_universe


def test_universe_has_the_authoritative_13_station_code_pairs() -> None:
    stations = load_universe()
    assert len(stations) == 13
    assert [(station.hdd_code, station.cdd_code) for station in stations] == [
        ("H1", "K1"),
        ("HW", "KW"),
        ("LP", "KP"),
        ("H2", "K2"),
        ("H3", "K3"),
        ("H5", "K5"),
        ("HR", "KR"),
        ("H0", "K0"),
        ("HQ", "KQ"),
        ("H4", "K4"),
        ("H6", "K6"),
        ("H7", "K7"),
        ("HS", "KS"),
    ]
    assert all(station.multiplier_usd == 20 and station.base_f == 65 for station in stations)


def test_calendar_is_exactly_the_14_listed_monthly_pairs() -> None:
    assert [(pair.index, pair.month) for pair in PAIRS] == [
        ("HDD", 10),
        ("HDD", 11),
        ("HDD", 12),
        ("HDD", 1),
        ("HDD", 2),
        ("HDD", 3),
        ("HDD", 4),
        ("CDD", 4),
        ("CDD", 5),
        ("CDD", 6),
        ("CDD", 7),
        ("CDD", 8),
        ("CDD", 9),
        ("CDD", 10),
    ]
    assert len(STRIPS) == 8
    assert season_of(Pair("HDD", 12), 2025, 12) == 2025
    assert season_of(Pair("HDD", 1), 2026, 1) == 2026
    assert season_of(Pair("HDD", 1), 2026, 2) is None
    with pytest.raises(ValueError, match="not a listed"):
        season_of(Pair("HDD", 7), 2026, 7)


def test_calendar_dates_handle_january_and_weekend_settlement() -> None:
    january = Pair("HDD", 1)
    assert as_of(january, 2026) == date(2025, 12, 1)
    assert fit_through(january, 2026) == date(2025, 11, 30)
    # January 2026 ends on Saturday: the second following weekday is Tuesday.
    assert settlement_date(january, 2026) == date(2026, 2, 3)
    assert as_of(Pair("CDD", 7), 2026) == date(2026, 6, 1)
    assert fit_through(Pair("CDD", 7), 2026) == date(2026, 5, 31)


def test_degree_days_and_monthly_sum_are_hand_computable() -> None:
    tbar = np.array([60.0, 65.0, 70.0, 64.5, 65.5])
    np.testing.assert_allclose(daily_hdd(tbar), [5, 0, 0, 0.5, 0])
    np.testing.assert_allclose(daily_cdd(tbar), [0, 0, 5, 0, 0.5])
    daily = np.column_stack((daily_hdd(tbar), daily_cdd(tbar)))
    np.testing.assert_allclose(monthly_index(daily, [True, False, True, False, True]), [5, 5.5])


def test_monthly_index_requires_a_matching_one_dimensional_mask() -> None:
    with pytest.raises(ValueError, match="month_mask"):
        monthly_index(np.ones((3, 2)), np.array([[True, False, True]]))
    with pytest.raises(ValueError, match="month_mask"):
        monthly_index(np.ones((3, 2)), np.array([True, False]))


def test_terminal_cashflows_and_optional_caps() -> None:
    index = np.array([50.0, 65.0, 80.0])
    np.testing.assert_allclose(call(index, 65), [0, 0, 300])
    np.testing.assert_allclose(put(index, 65), [300, 0, 0])
    np.testing.assert_allclose(futures(index, 65), [-300, 0, 300])
    np.testing.assert_allclose(call(index, 65, cap=125), [0, 0, 125])
    with pytest.raises(ValueError, match="non-negative"):
        call(index, 65, -1)
