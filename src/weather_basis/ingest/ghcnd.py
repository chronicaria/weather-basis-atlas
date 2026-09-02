"""GHCN-Daily station parsing and the project's station-QC convention.

The NOAA access CSV contains temperatures in tenths of degrees Celsius.  The
weather contracts, however, use the mean of the *integer Fahrenheit* maximum
and minimum.  Keeping that distinction here makes the later index calculation
both reproducible and faithful to the stated replication rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from weather_basis.config import Config
    from weather_basis.http import FetchResult


_GHCND_ACCESS = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access"
_REQUIRED_COLUMNS = ("DATE", "TMAX", "TMAX_ATTRIBUTES", "TMIN", "TMIN_ATTRIBUTES")


@dataclass(frozen=True)
class StationQC:
    """QC output for one station.

    ``daily`` retains original-missing and gap-fill flags, while ``monthly``
    is the authoritative eligibility table for the station index panel.
    """

    daily: pd.DataFrame
    monthly: pd.DataFrame

    @property
    def days(self) -> pd.DataFrame:
        """Backward-friendly descriptive alias for :attr:`daily`."""
        return self.daily

    @property
    def months(self) -> pd.DataFrame:
        """Backward-friendly descriptive alias for :attr:`monthly`."""
        return self.monthly


def fetch_station(ghcnd_id: str, raw_root: Path) -> FetchResult:
    """Fetch one NOAA GHCN-Daily access CSV into ``raw_root``.

    Cache, host allow-list, checksum, and refresh policy deliberately belong
    to the shared HTTP helper rather than this station-specific wrapper.
    """
    from weather_basis.http import fetch

    station_id = _validate_station_id(ghcnd_id)
    return fetch(
        f"{_GHCND_ACCESS}/{station_id}.csv",
        Path(raw_root) / f"{station_id}.csv",
        allow_hosts=frozenset({"www.ncei.noaa.gov"}),
    )


def parse_station(path: Path) -> pd.DataFrame:
    """Parse the GHCN fields used by the station panel without losing flags."""
    path = Path(path)
    header = pd.read_csv(path, nrows=0)
    missing = set(_REQUIRED_COLUMNS).difference(header.columns)
    if missing:
        raise ValueError(f"{path} is missing required GHCN columns: {sorted(missing)}")

    raw = pd.read_csv(path, usecols=list(_REQUIRED_COLUMNS), dtype={"DATE": "string"})
    dates = pd.to_datetime(raw["DATE"], format="%Y-%m-%d", errors="coerce")
    if dates.isna().any():
        raise ValueError(f"{path} contains an invalid DATE")

    out = pd.DataFrame(
        {
            "date": dates,
            "tmax_tenths_c": pd.to_numeric(raw["TMAX"], errors="coerce"),
            "tmin_tenths_c": pd.to_numeric(raw["TMIN"], errors="coerce"),
        }
    )
    tmax = _split_attributes(raw["TMAX_ATTRIBUTES"])
    tmin = _split_attributes(raw["TMIN_ATTRIBUTES"])
    out["tmax_qflag"] = tmax["qflag"]
    out["tmin_qflag"] = tmin["qflag"]
    out["tmax_sflag"] = tmax["sflag"]
    out["tmin_sflag"] = tmin["sflag"]
    return out.sort_values("date", kind="stable").reset_index(drop=True)


def to_integer_f(tenths_c: np.ndarray, *, tolerance: float) -> tuple[np.ndarray, np.ndarray]:
    """Convert tenths-C observations to integer Fahrenheit and flag deviations.

    Missing observations remain ``NaN`` and are not themselves deviation
    flags; missingness is handled separately by :func:`qc_station`.
    """
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    values = np.asarray(tenths_c, dtype=float)
    fahrenheit = values / 10.0 * 9.0 / 5.0 + 32.0
    finite = np.isfinite(fahrenheit)
    rounded = np.full(fahrenheit.shape, np.nan, dtype=float)
    # Decimal half-up is the project convention, and avoids NumPy's
    # banker's rounding if a non-integer source lands exactly on a half.
    rounded[finite] = np.floor(fahrenheit[finite] + 0.5)
    flags = np.zeros(fahrenheit.shape, dtype=bool)
    flags[finite] = np.abs(fahrenheit[finite] - rounded[finite]) > tolerance
    return rounded, flags


def qc_station(df: pd.DataFrame, cfg: Config) -> StationQC:
    """Apply integer-F conversion, short-gap filling, and monthly QC.

    Enforces build-plan Section 4.5: a missing element invalidates that day;
    only interior runs at most ``max_gap_days`` are interpolated; a month with
    more than ``max_missing_share`` original missing days or a longer run is
    excluded.  The most recent complete months are labelled provisional.
    """
    required = {
        "date",
        "tmax_tenths_c",
        "tmin_tenths_c",
        "tmax_qflag",
        "tmin_qflag",
        "tmax_sflag",
        "tmin_sflag",
    }
    absent = required.difference(df.columns)
    if absent:
        raise ValueError(f"station frame is missing required columns: {sorted(absent)}")
    if df.empty:
        empty_daily = pd.DataFrame(columns=_DAILY_COLUMNS)
        empty_monthly = pd.DataFrame(columns=_MONTHLY_COLUMNS)
        return StationQC(empty_daily, empty_monthly)

    tolerance = float(_station_setting(cfg, "integer_f_tolerance", 0.10))
    max_gap = int(_station_setting(cfg, "max_gap_days", 2))
    max_missing_share = float(_station_setting(cfg, "max_missing_share", 0.05))
    provisional_months = int(_station_setting(cfg, "provisional_months", 2))
    if max_gap < 0 or not 0 <= max_missing_share <= 1 or provisional_months < 0:
        raise ValueError("invalid station QC settings")

    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="raise").dt.normalize()
    if work["date"].duplicated().any():
        raise ValueError("station frame has duplicate dates")
    work = work.sort_values("date", kind="stable").set_index("date")
    # Include partial boundary months as missing.  This is what makes a
    # station's ``first_complete_month`` computable from QC rather than from
    # an assumption about the first row in a source file.
    start = work.index.min().to_period("M").start_time
    end = work.index.max().to_period("M").end_time.normalize()
    full_index = pd.date_range(start, end, freq="D")
    work = work.reindex(full_index)
    work.index.name = "date"

    max_f, max_dev = to_integer_f(work["tmax_tenths_c"].to_numpy(), tolerance=tolerance)
    min_f, min_dev = to_integer_f(work["tmin_tenths_c"].to_numpy(), tolerance=tolerance)
    max_bad_q = _nonblank(work["tmax_qflag"])
    min_bad_q = _nonblank(work["tmin_qflag"])
    original_missing = (~np.isfinite(max_f)) | (~np.isfinite(min_f)) | max_bad_q | min_bad_q

    # Mark any invalid element as unavailable before interpolating each
    # element independently.  A day is only considered filled if both are
    # then available, preserving the max/min arithmetic-mean definition.
    max_work = pd.Series(max_f, index=work.index).mask(max_bad_q)
    min_work = pd.Series(min_f, index=work.index).mask(min_bad_q)
    run_lengths = _run_lengths(original_missing)
    fillable = original_missing & (run_lengths <= max_gap)
    max_filled = max_work.interpolate(method="linear", limit_area="inside")
    min_filled = min_work.interpolate(method="linear", limit_area="inside")
    max_out = _round_half_up(max_filled.to_numpy())
    min_out = _round_half_up(min_filled.to_numpy())
    gap_filled = fillable & np.isfinite(max_out) & np.isfinite(min_out)
    # Long or end-of-record gaps are never permitted to leak through merely
    # because interpolation happened to produce a value.
    max_out[original_missing & ~gap_filled] = np.nan
    min_out[original_missing & ~gap_filled] = np.nan

    daily = pd.DataFrame(
        {
            "date": work.index,
            "tmax_f": max_out,
            "tmin_f": min_out,
            "tbar_f": (max_out + min_out) / 2.0,
            "missing": original_missing,
            "gap_filled": gap_filled,
            "tmax_integer_f_flag": max_dev,
            "tmin_integer_f_flag": min_dev,
            "tmax_qflag": work["tmax_qflag"].fillna("").astype(str).to_numpy(),
            "tmin_qflag": work["tmin_qflag"].fillna("").astype(str).to_numpy(),
            "tmax_sflag": work["tmax_sflag"].fillna("").astype(str).to_numpy(),
            "tmin_sflag": work["tmin_sflag"].fillna("").astype(str).to_numpy(),
        }
    )
    monthly = _monthly_qc(daily, max_gap=max_gap, max_missing_share=max_missing_share)
    if provisional_months:
        provisional = _last_complete_months(daily["date"], provisional_months)
        monthly.loc[
            monthly[["year", "month"]].apply(tuple, axis=1).isin(provisional)
            & (monthly["qc_status"] != "excluded"),
            "qc_status",
        ] = "provisional"
    # Avoid mutating the public daily schema with temporary grouping columns.
    month_keys = pd.DataFrame({"year": daily["date"].dt.year, "month": daily["date"].dt.month})
    daily["qc_status"] = pd.merge(
        month_keys, monthly[["year", "month", "qc_status"]], on=["year", "month"], how="left"
    )["qc_status"].to_numpy()
    return StationQC(daily.loc[:, _DAILY_COLUMNS], monthly.loc[:, _MONTHLY_COLUMNS])


def _split_attributes(values: pd.Series) -> pd.DataFrame:
    """Return GHCN's mflag/qflag/sflag fields, tolerating blank attributes."""
    fields = values.fillna("").astype(str).str.split(",", expand=True)
    fields = fields.reindex(columns=range(3), fill_value="")
    return pd.DataFrame(
        {
            "qflag": fields[1].fillna("").astype(str).str.strip(),
            "sflag": fields[2].fillna("").astype(str).str.strip(),
        }
    )


def _nonblank(values: pd.Series) -> np.ndarray:
    return values.fillna("").astype(str).str.strip().ne("").to_numpy()


def _round_half_up(values: np.ndarray) -> np.ndarray:
    out = np.asarray(values, dtype=float).copy()
    finite = np.isfinite(out)
    out[finite] = np.floor(out[finite] + 0.5)
    return out


def _run_lengths(mask: np.ndarray) -> np.ndarray:
    """Length of the contiguous true run containing each position (else zero)."""
    mask = np.asarray(mask, dtype=bool)
    result = np.zeros(mask.size, dtype=int)
    start = 0
    while start < mask.size:
        if not mask[start]:
            start += 1
            continue
        end = start + 1
        while end < mask.size and mask[end]:
            end += 1
        result[start:end] = end - start
        start = end
    return result


def _monthly_qc(daily: pd.DataFrame, *, max_gap: int, max_missing_share: float) -> pd.DataFrame:
    keyed = daily.assign(year=daily["date"].dt.year, month=daily["date"].dt.month)
    rows: list[dict[str, Any]] = []
    for (year, month), group in keyed.groupby(["year", "month"], sort=True):
        missing = group["missing"].to_numpy(dtype=bool)
        longest = int(_run_lengths(missing).max(initial=0))
        n_missing = int(missing.sum())
        n_days = int(len(group))
        excluded = n_missing / n_days > max_missing_share or longest > max_gap
        status = (
            "excluded" if excluded else ("gap_filled" if group["gap_filled"].any() else "complete")
        )
        realtime = group[["tmax_sflag", "tmin_sflag"]].isin({"H", "A"}).any(axis=1).sum()
        rows.append(
            {
                "year": int(year),
                "month": int(month),
                "n_days": n_days,
                "n_missing": n_missing,
                "longest_gap": longest,
                "n_gap_filled": int(group["gap_filled"].sum()),
                "qc_status": status,
                "n_realtime_flag": int(realtime),
                "n_integer_f_flag": int(
                    group["tmax_integer_f_flag"].sum() + group["tmin_integer_f_flag"].sum()
                ),
            }
        )
    return pd.DataFrame(rows)


def _last_complete_months(dates: pd.Series, n: int) -> set[tuple[int, int]]:
    all_dates = pd.DatetimeIndex(dates)
    if all_dates.empty:
        return set()
    candidates: list[tuple[int, int]] = []
    for period in pd.period_range(
        all_dates.min().to_period("M"), all_dates.max().to_period("M"), freq="M"
    ):
        expected = pd.date_range(period.start_time, period.end_time, freq="D")
        if expected.isin(all_dates).all():
            candidates.append((period.year, period.month))
    return set(candidates[-n:])


def _station_setting(cfg: Any, name: str, default: Any) -> Any:
    station = cfg.get("station", {}) if isinstance(cfg, dict) else getattr(cfg, "station", {})
    return (
        station.get(name, default) if isinstance(station, dict) else getattr(station, name, default)
    )


def _validate_station_id(ghcnd_id: str) -> str:
    station_id = str(ghcnd_id).strip().upper()
    if not station_id or any(
        char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for char in station_id
    ):
        raise ValueError(f"invalid GHCN station id: {ghcnd_id!r}")
    return station_id


_DAILY_COLUMNS = [
    "date",
    "tmax_f",
    "tmin_f",
    "tbar_f",
    "missing",
    "gap_filled",
    "tmax_integer_f_flag",
    "tmin_integer_f_flag",
    "tmax_qflag",
    "tmin_qflag",
    "tmax_sflag",
    "tmin_sflag",
    "qc_status",
]
_MONTHLY_COLUMNS = [
    "year",
    "month",
    "n_days",
    "n_missing",
    "longest_gap",
    "n_gap_filled",
    "qc_status",
    "n_realtime_flag",
    "n_integer_f_flag",
]
