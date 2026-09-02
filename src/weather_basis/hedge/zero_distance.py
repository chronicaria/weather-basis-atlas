"""Index-definition basis at a listed station's own county (plan section 6.6)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from weather_basis.hedge.atlas import _metrics


def station_own_county_table(
    pair: str,
    station_ids: np.ndarray,
    own_county_index: np.ndarray,
    residuals: np.ndarray,
    county_anomalies: np.ndarray,
    seasons: np.ndarray,
) -> pd.DataFrame:
    """Return one zero-distance row per station, with explicit non-evaluable rows."""
    stations = np.asarray(station_ids).astype(str)
    own = np.asarray(own_county_index, dtype=int)
    r = np.asarray(residuals, dtype=float)
    a = np.asarray(county_anomalies, dtype=float)
    years = np.asarray(seasons)
    if (
        r.ndim != 3
        or a.shape != r.shape[:2]
        or own.shape != (r.shape[2],)
        or years.shape != (r.shape[0],)
    ):
        raise ValueError("incompatible station/county rolling arrays")
    rows = []
    for j, station in enumerate(stations):
        m = _metrics(r[:, own[j], j], a[:, own[j]], years)
        rows.append(
            {
                "pair": pair,
                "station": station,
                "fips_index": int(own[j]),
                "he": m["he"],
                "rmse": m["rmse"],
                "es90_upper": m["es90_upper"],
                "es90_lower": m["es90_lower"],
                "worst": m["worst"],
                "worst_season": m["worst_season"],
                "n_test": m["n_test"],
                "not_evaluable": bool(m["n_test"] == 0),
            }
        )
    return pd.DataFrame(rows)
