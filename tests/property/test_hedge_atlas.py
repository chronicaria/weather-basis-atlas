"""Property coverage for plan Sections 6.4 and 6.5."""

from __future__ import annotations

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from weather_basis.hedge.bootstrap import year_block_bootstrap


@given(
    st.lists(st.integers(-100, 100).map(float), min_size=3, max_size=30)
)
def test_self_hedge_has_effectiveness_at_most_and_equal_to_one(values: list[float]) -> None:
    """Plan section 6.9: a series hedged by itself has HE one, and HE never exceeds one."""
    exposure = np.asarray(values, dtype=float)[:, None]
    if np.ptp(exposure) == 0:
        return
    result = year_block_bootstrap(
        np.zeros_like(exposure),
        np.zeros_like(exposure),
        np.zeros_like(exposure)[:, :, None],
        exposure,
        B=10,
        seed=np.random.SeedSequence(19),
    )
    assert np.nanmax(result.he_pit) <= 1.0 + 1e-12
    assert np.allclose(result.he_pit[np.isfinite(result.he_pit)], 1.0)
