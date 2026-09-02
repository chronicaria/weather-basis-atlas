"""Property tests enforcing build-plan Sections 8.1 and 8.4."""

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from weather_basis.pricing.coherence import check_distribution
from weather_basis.pricing.distribution import SortedSamples


@given(
    st.lists(
        st.floats(min_value=0, max_value=5000, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=80,
    ),
    st.lists(
        st.floats(min_value=0, max_value=6000, allow_nan=False, allow_infinity=False),
        min_size=3,
        max_size=40,
    ),
)
def test_empirical_option_identities_hold(values: list[float], strikes: list[float]) -> None:
    """Section 8.4: empirical calls and puts obey all gated shape identities."""
    samples = SortedSamples(np.array(values, dtype=np.float32))
    assert check_distribution(samples, np.array(strikes), 20.0).ok
