"""Deterministic bounded quote-table writer."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def write_quote_rows(rows: list[dict[str, object]], path: Path) -> Path:
    if not rows:
        raise ValueError("quote writer requires at least one row")
    columns = sorted({key for row in rows for key in row})
    if any(set(row) != set(columns) for row in rows):
        raise ValueError("quote rows must have identical fields")
    frame = pd.DataFrame(rows, columns=columns)
    numeric = frame.select_dtypes(include=[np.number])
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("quote rows cannot contain non-finite numeric values")
    sort_columns = [key for key in ("fips", "pair", "payoff", "strike") if key in columns]
    if sort_columns:
        frame = frame.sort_values(sort_columns, kind="mergesort")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path
