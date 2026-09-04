"""Memory-mapped daily county panels assembled from nClimGrid monthly files."""

from __future__ import annotations

import calendar
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from .nclimgrid import Month, parse_month

if TYPE_CHECKING:
    pass


class PanelError(ValueError):
    """Raised when a monthly input cannot form a coherent daily panel."""


@dataclass(frozen=True)
class Panel:
    """A daily, date-major panel backed by an ``.npy`` memory map."""

    values: np.ndarray
    dates: np.ndarray
    fips: np.ndarray


@dataclass(frozen=True)
class PanelReport:
    """Summary of a successfully built panel."""

    variable: str
    path: Path
    n_days: int
    n_counties: int
    nan_count: int
    first_date: date
    last_date: date


def _month_path(raw_root: Path, variable: str, month: Month) -> Path:
    filename = f"{variable}-{month.year:04d}{month.month:02d}-cty-scaled.csv"
    candidates = (
        raw_root / "averages" / str(month.year) / filename,
        raw_root / str(month.year) / filename,
        raw_root / filename,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise PanelError(f"Missing nClimGrid input for {variable} {month}: {candidates[0]}")


def _county_fips(counties: pd.DataFrame) -> np.ndarray:
    column = next((name for name in ("fips", "county_fips") if name in counties.columns), None)
    if column is None:
        raise PanelError("County dimension needs fips or county_fips")
    values = counties[column].astype("string").str.zfill(5).to_numpy(dtype="U5")
    if len(values) == 0 or len(np.unique(values)) != len(values):
        raise PanelError("County dimension is empty or contains duplicate FIPS")
    if not np.array_equal(values, np.sort(values)):
        raise PanelError("County dimension must be sorted by ascending FIPS")
    return values


def _write_npy(path: Path, array: np.ndarray) -> None:
    """Atomically persist an array without relying on a process-local mmap."""

    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    with partial.open("wb") as output:
        np.save(output, array, allow_pickle=False)
    os.replace(partial, path)


def build_panel(
    variable: str,
    months: list[Month],
    raw_root: Path,
    out_dir: Path,
    counties: pd.DataFrame,
    *,
    date_axis: np.ndarray | None = None,
) -> PanelReport:
    """Build one date-major float32 county panel from validated monthly files."""

    if variable not in {"tavg", "tmax", "tmin"}:
        raise PanelError(f"Unsupported panel variable: {variable!r}")
    if not months:
        raise PanelError("Cannot build a panel without months")
    ordered_months = sorted(months, key=lambda item: (item.year, item.month))
    if len(set(ordered_months)) != len(ordered_months):
        raise PanelError("Panel months must be unique")
    fips = _county_fips(counties)
    if date_axis is None:
        day_count = sum(calendar.monthrange(item.year, item.month)[1] for item in ordered_months)
        dates = np.empty(day_count, dtype="datetime64[D]")
    else:
        dates = np.asarray(date_axis, dtype="datetime64[D]")
        if dates.ndim != 1 or dates.size == 0:
            raise PanelError("Panel date axis must be a non-empty vector")
        if np.any(np.diff(dates.astype("int64")) != 1):
            raise PanelError("Panel date axis must be calendar-contiguous")
        day_count = dates.size
    values = np.full((day_count, len(fips)), np.nan, dtype=np.float32)
    offset = 0
    state_codes = _state_codes(counties)

    for month in ordered_months:
        parsed, month_counties = parse_month(
            _month_path(raw_root, variable, month), variable, month, state_codes
        )
        if parsed.shape[0] != calendar.monthrange(month.year, month.month)[1]:
            raise PanelError(f"{month} has unexpected day count {parsed.shape[0]}")
        source_fips = np.asarray([str(item.fips).zfill(5) for item in month_counties], dtype="U5")
        if len(np.unique(source_fips)) != len(source_fips):
            raise PanelError(f"{month} repeats a county FIPS")
        position = {item: idx for idx, item in enumerate(source_fips)}
        absent = sorted(set(fips) - set(source_fips))
        extra = sorted(set(source_fips) - set(fips))
        if absent or extra:
            raise PanelError(
                f"{month} county dimension differs (absent={absent[:3]}, extra={extra[:3]})"
            )
        indices = np.asarray([position[item] for item in fips], dtype=np.intp)
        width = parsed.shape[0]
        start = np.datetime64(f"{month.year:04d}-{month.month:02d}-01")
        if date_axis is not None:
            offset = int(np.searchsorted(dates, start))
            if offset >= dates.size or dates[offset] != start or offset + width > dates.size:
                raise PanelError(f"{month} falls outside the requested panel date axis")
        # nClimGrid county files are Celsius; all public panel values are °F.
        values[offset : offset + width] = parsed[:, indices] * np.float32(9 / 5) + np.float32(32)
        if date_axis is None:
            dates[offset : offset + width] = start + np.arange(width).astype("timedelta64[D]")
            offset += width

    if np.any(np.diff(dates.astype("int64")) != 1):
        raise PanelError("Panel months are not calendar-contiguous")
    _write_npy(out_dir / f"{variable}_f32.npy", values)
    dates_path, fips_path = out_dir / "dates.npy", out_dir / "fips.npy"
    if dates_path.exists() and not np.array_equal(np.load(dates_path, mmap_mode="r"), dates):
        raise PanelError("Existing dates.npy conflicts with the requested panel")
    if fips_path.exists() and not np.array_equal(np.load(fips_path, mmap_mode="r"), fips):
        raise PanelError("Existing fips.npy conflicts with the county dimension")
    _write_npy(dates_path, dates)
    _write_npy(fips_path, fips)
    return PanelReport(
        variable=variable,
        path=out_dir / f"{variable}_f32.npy",
        n_days=values.shape[0],
        n_counties=values.shape[1],
        nan_count=int(np.isnan(values).sum()),
        first_date=pd.Timestamp(dates[0]).date(),
        last_date=pd.Timestamp(dates[-1]).date(),
    )


def _state_codes(counties: pd.DataFrame) -> dict[str, str]:
    """Extract the NCEI-to-FIPS state crosswalk carried by the county table."""

    ncei_column = next(
        (name for name in ("ncei_code", "ncei_county_code") if name in counties), None
    )
    fips_column = next((name for name in ("fips", "county_fips") if name in counties), None)
    if ncei_column is None or fips_column is None:
        # ``parse_month`` tests may supply a parser that does not use this map;
        # production tables always have both fields.
        return {}
    pairs = zip(
        counties[ncei_column].astype("string"), counties[fips_column].astype("string"), strict=True
    )
    result: dict[str, str] = {}
    for ncei, fips in pairs:
        if len(ncei) >= 2 and len(fips) >= 2:
            # NCEI 18511 is the District of Columbia exception inside the
            # otherwise-Maryland (18 -> 24) namespace; it cannot define the
            # state-level crosswalk used for the rest of prefix 18.
            if str(ncei).zfill(5) == "18511":
                continue
            result.setdefault(str(ncei).zfill(5)[:2], str(fips).zfill(5)[:2])
    return result


def load_panel(variable: str, *, through: date | None = None) -> Panel:
    """Open a built panel as read-only memmaps, optionally ending at ``through``."""

    root = Path("data/panel")
    values_path = root / f"{variable}_f32.npy"
    dates_path, fips_path = root / "dates.npy", root / "fips.npy"
    if not values_path.is_file() or not dates_path.is_file() or not fips_path.is_file():
        raise FileNotFoundError(f"Panel files are missing for {variable}")
    values = np.load(values_path, mmap_mode="r", allow_pickle=False)
    dates = np.load(dates_path, mmap_mode="r", allow_pickle=False)
    fips = np.load(fips_path, mmap_mode="r", allow_pickle=False)
    if (
        values.ndim != 2
        or dates.ndim != 1
        or fips.ndim != 1
        or values.shape != (len(dates), len(fips))
    ):
        raise PanelError(f"Inconsistent panel dimensions for {variable}")
    if through is not None:
        end = np.searchsorted(dates, np.datetime64(through), side="right")
        values, dates = values[:end], dates[:end]
    return Panel(values=values, dates=dates, fips=fips)
