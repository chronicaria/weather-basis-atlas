"""Property tests enforcing Weather Basis Atlas build plan Sections 6.3 and 6.9."""

from __future__ import annotations

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from weather_basis.hedge.metrics import he, rmse


@given(
    st.lists(st.floats(-1000, 1000, allow_nan=False, allow_infinity=False), min_size=2, max_size=80)
)
def test_he_never_exceeds_one(values: list[float]) -> None:
    """Section 6.9: pooled hedge effectiveness is bounded above by one."""
    target = np.asarray(values)
    residual = target - np.mean(target)
    result = he(residual, target)
    if np.nanvar(target) > 0.0:
        assert result <= 1.0 + 1e-12


@given(
    st.lists(st.floats(-1000, 1000, allow_nan=False, allow_infinity=False), min_size=2, max_size=80)
)
def test_self_hedge_has_unit_effectiveness(values: list[float]) -> None:
    """Section 6.9: a zero-residual self hedge has HE exactly one when defined."""
    target = np.asarray(values)
    if np.var(target) > 0.0:
        assert he(np.zeros_like(target), target) == 1.0


@given(
    st.lists(st.floats(-1e6, 1e6, allow_nan=False, allow_infinity=False), min_size=1, max_size=80)
)
def test_rmse_is_nonnegative(values: list[float]) -> None:
    """Section 6.9: residual RMSE is always non-negative."""
    assert rmse(np.asarray(values)) >= 0.0
