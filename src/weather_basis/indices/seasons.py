"""Calendar-month grouping and stable long-format index result helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import numpy as np
import pandas as pd


def pair_parts(pair: object) -> tuple[str, int]:
    """Extract ``(HDD|CDD, month)`` from the project's Pair or a ``HDD-01`` key."""
    if isinstance(pair, str):
        kind, separator, month = pair.upper().partition("-")
        if not separator:
            raise ValueError(f"invalid pair key: {pair!r}")
    elif isinstance(pair, Mapping):
        kind, month = pair["kind"], pair["month"]
    elif isinstance(pair, tuple) and len(pair) == 2:
        kind, month = pair
    else:
        kind = getattr(pair, "index", getattr(pair, "kind", getattr(pair, "index_type", None)))
        month = getattr(pair, "month", None)
    kind = str(kind).upper()
    try:
        month = int(month)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid pair: {pair!r}") from exc
    if kind not in {"HDD", "CDD"} or not 1 <= month <= 12:
        raise ValueError(f"invalid pair: {pair!r}")
    return kind, month


def pair_key(pair: object) -> str:
    """Return the canonical contract key (for example ``CDD-07``)."""
    kind, month = pair_parts(pair)
    return f"{kind}-{month:02d}"


def date_parts(dates: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return calendar years and months for day-resolution datetime arrays."""
    raw = np.asarray(dates)
    if raw.ndim != 1:
        raise ValueError("dates must be one-dimensional")
    days = raw.astype("datetime64[D]")
    if np.isnat(days).any():
        raise ValueError("dates cannot contain NaT")
    months = days.astype("datetime64[M]")
    return months.astype("datetime64[Y]").astype(int) + 1970, (months.astype(int) % 12) + 1


def seasons_for_pair(dates: np.ndarray, pair: object) -> np.ndarray:
    """Return contract-year labels, with ``-1`` outside the pair's month."""
    _, month = pair_parts(pair)
    years, months = date_parts(dates)
    return np.where(months == month, years, -1)


def month_mask(dates: np.ndarray, pair: object) -> np.ndarray:
    """Select daily panel rows belonging to the pair's calendar month."""
    return seasons_for_pair(dates, pair) >= 0


def index_frame(
    pair: object,
    identifiers: Iterable[object],
    seasons: np.ndarray,
    index: np.ndarray,
    *,
    identifier_name: str,
    normal: np.ndarray | None = None,
    anomalies: np.ndarray | None = None,
    n_prior: np.ndarray | None = None,
) -> pd.DataFrame:
    """Build deterministic long-format rows for one contract pair.

    Inputs use the panel convention ``(season, series)``.  The dataframe is
    sorted by identifier then season, which is also the deterministic Parquet
    row order used by result writers.
    """
    ids = np.asarray(list(identifiers), dtype=object)
    season_values = np.asarray(seasons, dtype=np.int64)
    values = np.asarray(index, dtype=float)
    if values.ndim != 2 or values.shape != (season_values.size, ids.size):
        raise ValueError("index must have shape (len(seasons), len(identifiers))")

    fields: dict[str, object] = {
        "pair": np.repeat(pair_key(pair), values.size),
        identifier_name: np.tile(ids, season_values.size),
        "season": np.repeat(season_values, ids.size),
        "index": values.reshape(-1),
    }
    for name, array in (("normal", normal), ("anomaly", anomalies), ("n_prior", n_prior)):
        if array is not None:
            array = np.asarray(array)
            if array.shape != values.shape:
                raise ValueError(f"{name} must have shape matching index")
            fields[name] = array.reshape(-1)
    return (
        pd.DataFrame(fields)
        .sort_values([identifier_name, "season"], kind="stable")
        .reset_index(drop=True)
    )
