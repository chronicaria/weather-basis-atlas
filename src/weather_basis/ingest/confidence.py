"""Data-quality confidence proxies independent of hedge-fit statistics.

Confidence is descriptive metadata, not an input to model selection.  It is
based only on the historical GHCN station network and observed county-panel
variance, as required by the preregistered data-layer rule.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

EARTH_RADIUS_KM = 6_371.0088
MILES_TO_KM = 1.609344


class ConfidenceError(ValueError):
    """Raised for malformed station metadata or incompatible panel inputs."""


@dataclass(frozen=True)
class ConfidenceReport:
    """County-level station-density and variance-regime confidence output."""

    frame: pd.DataFrame
    decades: tuple[int, ...]


def haversine_km(
    lat_a: np.ndarray | float,
    lon_a: np.ndarray | float,
    lat_b: np.ndarray | float,
    lon_b: np.ndarray | float,
) -> np.ndarray:
    """Great-circle distance in kilometres, broadcasting over input arrays."""

    lat_a, lon_a, lat_b, lon_b = np.broadcast_arrays(lat_a, lon_a, lat_b, lon_b)
    phi_a, phi_b = np.deg2rad(lat_a.astype(float)), np.deg2rad(lat_b.astype(float))
    d_phi = phi_b - phi_a
    d_lambda = np.deg2rad(lon_b.astype(float) - lon_a.astype(float))
    a = np.sin(d_phi / 2) ** 2 + np.cos(phi_a) * np.cos(phi_b) * np.sin(d_lambda / 2) ** 2
    return EARTH_RADIUS_KM * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def load_ghcnd_inventory(path: Path) -> pd.DataFrame:
    """Parse NOAA's fixed-width GHCN inventory into element availability rows."""

    widths = [11, 9, 10, 5, 5, 5]
    names = ["ghcnd_id", "lat", "lon", "element", "first_year", "last_year"]
    frame = pd.read_fwf(
        path, widths=widths, names=names, dtype={"ghcnd_id": "string", "element": "string"}
    )
    frame["ghcnd_id"] = frame["ghcnd_id"].str.strip()
    frame["element"] = frame["element"].str.strip()
    for column in ("lat", "lon", "first_year", "last_year"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=names).copy()
    frame["first_year"] = frame["first_year"].astype(int)
    frame["last_year"] = frame["last_year"].astype(int)
    if frame.empty or (frame["first_year"] > frame["last_year"]).any():
        raise ConfidenceError("GHCN inventory is empty or has invalid year intervals")
    return frame.reset_index(drop=True)


def station_density_by_decade(
    counties: pd.DataFrame,
    inventory: pd.DataFrame,
    *,
    radius_miles: float = 30.0,
    decades: Iterable[int] | None = None,
) -> pd.DataFrame:
    """Count nearby stations with both TMAX and TMIN coverage in each decade.

    A station is available for a decade when both elements overlap at least one
    year of that decade.  This avoids treating a TMAX-only record as a daily
    temperature observation while preserving the intended long-run density
    proxy.
    """

    required_counties = {"fips", "lat", "lon"}
    missing = required_counties.difference(counties.columns)
    required_inventory = {"ghcnd_id", "lat", "lon", "element", "first_year", "last_year"}
    inv_missing = required_inventory.difference(inventory.columns)
    if missing or inv_missing or radius_miles <= 0:
        raise ConfidenceError("Invalid county/inventory fields or radius")
    if decades is None:
        first = int(inventory["first_year"].min() // 10 * 10)
        last = int(inventory["last_year"].max() // 10 * 10)
        decades = range(first, last + 1, 10)
    decade_values = tuple(sorted({int(value) for value in decades}))
    if not decade_values:
        raise ConfidenceError("At least one decade is required")

    elements = inventory[inventory["element"].isin(["TMAX", "TMIN"])].copy()
    grouped = elements.groupby(["ghcnd_id", "lat", "lon", "element"], as_index=False).agg(
        first_year=("first_year", "min"), last_year=("last_year", "max")
    )
    pivot = grouped.pivot(
        index=["ghcnd_id", "lat", "lon"], columns="element", values=["first_year", "last_year"]
    )
    if pivot.empty:
        stations = pd.DataFrame(columns=["ghcnd_id", "lat", "lon", "first_year", "last_year"])
    else:
        needed = [
            (key, element) for key in ("first_year", "last_year") for element in ("TMAX", "TMIN")
        ]
        pivot = pivot.dropna(subset=needed)
        stations = pivot.reset_index()
        stations.columns = [
            "ghcnd_id",
            "lat",
            "lon",
            "tmax_first",
            "tmin_first",
            "tmax_last",
            "tmin_last",
        ]
        stations["first_year"] = stations[["tmax_first", "tmin_first"]].max(axis=1).astype(int)
        stations["last_year"] = stations[["tmax_last", "tmin_last"]].min(axis=1).astype(int)
        stations = stations[stations["first_year"] <= stations["last_year"]]

    result = counties.loc[:, ["fips"]].copy()
    county_lat = pd.to_numeric(counties["lat"], errors="raise").to_numpy()
    county_lon = pd.to_numeric(counties["lon"], errors="raise").to_numpy()
    if stations.empty:
        nearby = np.empty((len(counties), 0), dtype=bool)
    else:
        nearby = (
            haversine_km(
                county_lat[:, None],
                county_lon[:, None],
                stations["lat"].to_numpy()[None, :],
                stations["lon"].to_numpy()[None, :],
            )
            <= radius_miles * MILES_TO_KM
        )
    for decade in decade_values:
        if stations.empty:
            active = np.zeros(0, dtype=bool)
        else:
            active = (stations["first_year"].to_numpy() <= decade + 9) & (
                stations["last_year"].to_numpy() >= decade
            )
        result[f"stations_within_30mi_{decade}"] = (nearby & active).sum(axis=1).astype("int16")
    return result


def variance_regime_ratio(
    values: np.ndarray,
    dates: np.ndarray,
    *,
    early: tuple[int, int] = (1951, 1970),
    late: tuple[int, int] = (2001, 2020),
) -> np.ndarray:
    """Return later/earlier within-year daily-temperature variance by county.

    Values are first demeaned by calendar year, so the proxy detects variance
    regime changes rather than warming trends.  A missing comparison window
    yields ``NaN`` rather than a fabricated confidence assessment.
    """

    values = np.asarray(values)
    dates = np.asarray(dates).astype("datetime64[D]")
    if values.ndim != 2 or dates.ndim != 1 or len(dates) != values.shape[0]:
        raise ConfidenceError("values must be (days, counties) with matching dates")
    years = dates.astype("datetime64[Y]").astype(int) + 1970

    def _variance(window: tuple[int, int]) -> np.ndarray:
        mask = (years >= window[0]) & (years <= window[1])
        if not mask.any():
            return np.full(values.shape[1], np.nan)
        selected, selected_years = values[mask].astype(float, copy=False), years[mask]
        residual = np.full_like(selected, np.nan, dtype=float)
        for year in np.unique(selected_years):
            rows = selected_years == year
            observations = selected[rows]
            n_observed = np.isfinite(observations).sum(axis=0)
            mean = np.divide(
                np.nansum(observations, axis=0),
                n_observed,
                out=np.full(values.shape[1], np.nan),
                where=n_observed > 0,
            )
            residual[rows] = observations - mean
        n_observed = np.isfinite(residual).sum(axis=0)
        return np.divide(
            np.nansum(residual**2, axis=0),
            n_observed - 1,
            out=np.full(values.shape[1], np.nan),
            where=n_observed > 1,
        )

    early_variance, late_variance = _variance(early), _variance(late)
    ratio = np.full(values.shape[1], np.nan)
    valid = np.isfinite(early_variance) & np.isfinite(late_variance) & (early_variance > 0)
    ratio[valid] = late_variance[valid] / early_variance[valid]
    return ratio


def assess_confidence(
    counties: pd.DataFrame,
    inventory: pd.DataFrame,
    values: np.ndarray,
    dates: np.ndarray,
    *,
    radius_miles: float = 30.0,
    decades: Iterable[int] | None = None,
    variance_bounds: tuple[float, float] = (0.5, 2.0),
) -> ConfidenceReport:
    """Compute the project confidence flag and its transparent components.

    ``not_assessed`` is reserved for incomplete historical windows.  Otherwise
    ``low`` means no nearby complete-temperature station in the most recent
    available decade, or a variance-regime ratio outside the declared broad
    screening range; remaining counties are ``standard``.
    """

    if variance_bounds[0] <= 0 or variance_bounds[0] >= variance_bounds[1]:
        raise ConfidenceError("variance_bounds must be positive and ordered")
    density = station_density_by_decade(
        counties, inventory, radius_miles=radius_miles, decades=decades
    )
    density_columns = [column for column in density if column.startswith("stations_within_30mi_")]
    ratio = variance_regime_ratio(values, dates)
    result = density.copy()
    result["variance_regime_ratio"] = ratio
    latest = (
        result[density_columns[-1]].to_numpy()
        if density_columns
        else np.zeros(len(result), dtype=int)
    )
    assessed = np.isfinite(ratio)
    result["confidence"] = np.where(
        ~assessed,
        "not_assessed",
        np.where(
            (latest == 0) | (ratio < variance_bounds[0]) | (ratio > variance_bounds[1]),
            "low",
            "standard",
        ),
    )
    return ConfidenceReport(
        frame=result,
        decades=tuple(int(column.rsplit("_", 1)[1]) for column in density_columns),
    )
