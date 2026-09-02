"""Station monthly HDD/CDD panels, respecting ingest QC month exclusions."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from weather_basis.indices.anomalies import anomaly, prior_counts, trailing_normal
from weather_basis.indices.seasons import date_parts, index_frame, pair_key, pair_parts

_UNUSABLE_QC = frozenset({"excluded", "provisional"})


def monthly_indices(
    tbar_f: np.ndarray,
    dates: np.ndarray,
    pairs: Iterable[object],
    *,
    station_ids: Iterable[object] | None = None,
    station_qc: pd.DataFrame | None = None,
    base_f: float = 65.0,
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Sum station daily degree days, returning NaN for unusable station-months."""
    values = np.asarray(tbar_f, dtype=float)
    if values.ndim != 2:
        raise ValueError("tbar_f must have shape (days, stations)")
    years, months = date_parts(dates)
    if values.shape[0] != years.size:
        raise ValueError("dates and tbar_f have different day counts")
    supplied_ids = list(station_ids) if station_ids is not None else np.arange(values.shape[1])
    ids = np.asarray(supplied_ids, dtype=object)
    if ids.size != values.shape[1]:
        raise ValueError("station_ids must have one value per station column")

    bad_months = _bad_months(station_qc, ids)
    result: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for pair in pairs:
        kind, month = pair_parts(pair)
        selected_years = np.unique(years[months == month])
        daily = (
            np.maximum(base_f - values, 0.0) if kind == "HDD" else np.maximum(values - base_f, 0.0)
        )
        out = np.full((selected_years.size, values.shape[1]), np.nan, dtype=np.float64)
        for row, year in enumerate(selected_years):
            selected = (years == year) & (months == month)
            # Any missing daily value makes the monthly result unavailable; QC
            # has already filled permitted short gaps and classified the rest.
            complete = np.isfinite(values[selected]).all(axis=0)
            out[row, complete] = daily[selected][:, complete].sum(axis=0)
            for column, station_id in enumerate(ids):
                if (station_id, int(year), month) in bad_months:
                    out[row, column] = np.nan
        result[pair_key(pair)] = (selected_years, out)
    return result


def _bad_months(qc: pd.DataFrame | None, station_ids: np.ndarray) -> set[tuple[object, int, int]]:
    if qc is None:
        return set()
    required = {"year", "month", "qc_status"}
    if not required.issubset(qc.columns):
        raise ValueError(f"station_qc must contain {sorted(required)}")
    if "ghcnd_id" in qc.columns:
        id_column = "ghcnd_id"
    elif "station_id" in qc.columns:
        id_column = "station_id"
    else:
        id_column = None
    if id_column is None:
        raise ValueError("station_qc must contain ghcnd_id or station_id")
    known = set(station_ids)
    rows = qc.loc[qc["qc_status"].isin(_UNUSABLE_QC), [id_column, "year", "month"]]
    return {
        (row[0], int(row[1]), int(row[2]))
        for row in rows.itertuples(index=False, name=None)
        if row[0] in known
    }


def build_station_frame(
    tbar_f: np.ndarray,
    dates: np.ndarray,
    station_ids: Iterable[object],
    pair: object,
    *,
    station_qc: pd.DataFrame | None = None,
    base_f: float = 65.0,
    window: int = 30,
    min_prior: int = 10,
) -> pd.DataFrame:
    """Build the Section 6.1 long station index/anomaly panel for one pair."""
    ids = list(station_ids)
    seasons, index = monthly_indices(
        tbar_f, dates, [pair], station_ids=ids, station_qc=station_qc, base_f=base_f
    )[pair_key(pair)]
    normal = trailing_normal(index, window=window, min_prior=min_prior)
    return index_frame(
        pair,
        ids,
        seasons,
        index,
        identifier_name="ghcnd_id",
        normal=normal,
        anomalies=anomaly(index, window=window, min_prior=min_prior),
        n_prior=prior_counts(index, window=window),
    )


build_indices = monthly_indices
