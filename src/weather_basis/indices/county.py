"""County monthly HDD/CDD index construction from the daily TAVG panel."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from weather_basis.indices.anomalies import anomaly, prior_counts, trailing_normal
from weather_basis.indices.seasons import date_parts, index_frame, pair_key, pair_parts


def monthly_indices(
    tbar_f: np.ndarray, dates: np.ndarray, pairs: Iterable[object], *, base_f: float = 65.0
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Sum daily county degree days into ``{pair: (seasons, index)}`` panels.

    ``tbar_f`` is ``(days, counties)``.  A county panel is complete by contract;
    a non-finite input therefore raises rather than silently manufacturing an
    annual result from partial daily data.
    """
    values = np.asarray(tbar_f, dtype=float)
    if values.ndim != 2:
        raise ValueError("tbar_f must have shape (days, counties)")
    years, months = date_parts(dates)
    if values.shape[0] != years.size:
        raise ValueError("dates and tbar_f have different day counts")
    if not np.isfinite(values).all():
        raise ValueError("county TAVG panel must not contain missing values")

    result: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for pair in pairs:
        kind, month = pair_parts(pair)
        selected_years = np.unique(years[months == month])
        daily = (
            np.maximum(base_f - values, 0.0) if kind == "HDD" else np.maximum(values - base_f, 0.0)
        )
        out = np.empty((selected_years.size, values.shape[1]), dtype=np.float64)
        for row, year in enumerate(selected_years):
            out[row] = daily[(years == year) & (months == month)].sum(axis=0)
        result[pair_key(pair)] = (selected_years, out)
    return result


def build_county_frame(
    tbar_f: np.ndarray,
    dates: np.ndarray,
    fips: Iterable[object],
    pair: object,
    *,
    base_f: float = 65.0,
    window: int = 30,
    min_prior: int = 15,
) -> pd.DataFrame:
    """Build the Section 6.1 long county index/anomaly panel for one pair."""
    seasons, index = monthly_indices(tbar_f, dates, [pair], base_f=base_f)[pair_key(pair)]
    normal = trailing_normal(index, window=window, min_prior=min_prior)
    return index_frame(
        pair,
        fips,
        seasons,
        index,
        identifier_name="fips",
        normal=normal,
        anomalies=anomaly(index, window=window, min_prior=min_prior),
        n_prior=prior_counts(index, window=window),
    )


build_indices = monthly_indices
