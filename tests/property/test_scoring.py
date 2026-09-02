"""Property tests enforcing plan Section 7.5 CRPS identities."""

from __future__ import annotations

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from weather_basis.models.scoring import crps_from_samples, unit_skill


@given(
    st.lists(st.floats(-100, 100, allow_nan=False, allow_infinity=False), min_size=1, max_size=40),
    st.floats(-100, 100, allow_nan=False, allow_infinity=False),
)
def test_crps_is_nonnegative_and_matches_double_sum(values: list[float], y: float) -> None:
    x = np.sort(np.asarray(values))
    actual = crps_from_samples(x, y)
    brute = np.mean(np.abs(x - y)) - np.mean(np.abs(x[:, None] - x[None, :])) / 2
    assert actual >= -1e-11
    assert np.isclose(actual, brute)


@given(st.floats(-100, 100, allow_nan=False, allow_infinity=False))
def test_crps_of_matching_point_mass_is_zero(y: float) -> None:
    assert crps_from_samples(np.array([y]), y) == 0.0


def test_unit_skill_pools_before_dividing() -> None:
    assert unit_skill(np.array([1.0, 2.0]), np.array([2.0, 4.0])) == 0.5
