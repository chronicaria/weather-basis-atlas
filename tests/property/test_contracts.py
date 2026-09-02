"""Property tests enforcing payoff and degree-day identities from plan Section 5.3."""

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from weather_basis.contracts.degree_days import daily_cdd, daily_hdd
from weather_basis.contracts.payoff import call, put

finite_temperatures = st.floats(
    min_value=-100, max_value=160, allow_nan=False, allow_infinity=False
)
finite_index = st.floats(min_value=0, max_value=4000, allow_nan=False, allow_infinity=False)


@given(tbar=finite_temperatures)
def test_hdd_minus_cdd_identity(tbar: float) -> None:
    """For every temperature, HDD minus CDD equals the base minus temperature."""
    hdd = daily_hdd(np.array([tbar]))[0]
    cdd = daily_cdd(np.array([tbar]))[0]
    assert np.isclose(hdd - cdd, 65.0 - tbar)
    assert hdd >= 0 and cdd >= 0


@given(index=finite_index, strike=finite_index, multiplier=st.floats(min_value=0, max_value=1000))
def test_call_put_bounds_and_parity(index: float, strike: float, multiplier: float) -> None:
    """Uncapped calls/puts are nonnegative and satisfy cash payoff parity."""
    c = call(index, strike, multiplier)
    p = put(index, strike, multiplier)
    assert c >= 0 and p >= 0
    assert np.isclose(c - p, multiplier * (index - strike))


@given(low=finite_index, high=finite_index, strike=finite_index)
def test_call_is_monotone_in_index(low: float, high: float, strike: float) -> None:
    """The call payoff is monotone in the terminal index."""
    low, high = sorted((low, high))
    assert call(low, strike) <= call(high, strike)
