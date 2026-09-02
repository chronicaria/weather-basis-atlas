"""Seasonal strip index panels assembled from registered monthly components."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from weather_basis.indices.anomalies import anomaly, prior_counts, trailing_normal
from weather_basis.indices.seasons import index_frame


def build_strip_frame(
    components: Iterable[tuple[pd.DataFrame, int]],
    *,
    strip: str,
    identifier_name: str,
    window: int,
    min_prior: int,
) -> pd.DataFrame:
    """Sum monthly indexes into a strip, with offsets relative to settlement year.

    Each component is a long monthly panel plus the source-season offset.  For
    example, HDD Nov--Mar uses offsets ``(-1, -1, 0, 0, 0)`` so its season is
    labelled by the March contract year.  A strip is unavailable whenever one
    component month is unavailable for that series.
    """
    parts = tuple(components)
    if not parts:
        raise ValueError("a strip needs at least one monthly component")
    identifiers = np.sort(parts[0][0][identifier_name].astype(str).unique())
    season_sets = []
    pivots = []
    for frame, offset in parts:
        required = {identifier_name, "season", "index"}
        if not required <= set(frame):
            raise ValueError(f"strip component is missing {sorted(required - set(frame))}")
        pivot = frame.assign(**{identifier_name: frame[identifier_name].astype(str)}).pivot(
            index="season", columns=identifier_name, values="index"
        )
        pivots.append((pivot.reindex(columns=identifiers), int(offset)))
        season_sets.append(set(pivot.index.to_numpy(dtype=int) - int(offset)))
    seasons = np.array(sorted(set.intersection(*season_sets)), dtype=int)
    if not len(seasons):
        raise ValueError(f"no common seasons for {strip}")
    values = np.zeros((len(seasons), len(identifiers)), dtype=float)
    for pivot, offset in pivots:
        values += pivot.reindex(index=seasons + offset, columns=identifiers).to_numpy(dtype=float)
    # Addition with NaN deliberately marks an incomplete station strip missing.
    normal = trailing_normal(values, window=window, min_prior=min_prior)
    # ``index_frame`` validates a monthly Pair key, while strips use CME suffix
    # codes such as HDD-X.  Reuse its deterministic long-format construction
    # and then replace only the identifier value.
    result = index_frame(
        "HDD-01",
        identifiers,
        seasons,
        values,
        identifier_name=identifier_name,
        normal=normal,
        anomalies=anomaly(values, window=window, min_prior=min_prior),
        n_prior=prior_counts(values, window=window),
    )
    result["pair"] = strip
    return result
