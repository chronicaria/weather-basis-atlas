"""Deterministic synthetic NOAA-shaped inputs for the CI fixture (plan Section 12.2).

The fixture is intentionally generated rather than checked in.  Its small,
known weather process makes it useful for exercising the real ingestion path
without presenting synthetic values as observations.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import numpy as np

FIXTURE_START = date(1951, 1, 1)
FIXTURE_END = date(1996, 12, 31)
DEFAULT_SEED = 20260901


@dataclass(frozen=True)
class FixturePaths:
    """Locations written by :func:`generate_fixture`, relative to its root."""

    root: Path
    raw: Path
    metadata: Path
    geography: Path
    counties: Path
    gazetteer: Path
    population: Path
    topojson: Path
    stations: tuple[Path, ...]


# FIPS are genuine county IDs.  DC is deliberately represented by NOAA's
# legacy 18511 code so the production remap is exercised.
_COUNTIES = (
    ("01001", "01001", "AL", "Autauga County", 32.54, -86.64),
    ("06001", "06001", "CA", "Alameda County", 37.65, -121.89),
    ("08001", "08001", "CO", "Adams County", 39.87, -104.34),
    ("18511", "11001", "DC", "District of Columbia", 38.91, -77.02),
    ("09001", "09001", "CT", "Fairfield County", 41.22, -73.37),
    ("12086", "12086", "FL", "Miami-Dade County", 25.62, -80.51),
    ("17031", "17031", "IL", "Cook County", 41.84, -87.82),
    ("19153", "19153", "IA", "Polk County", 41.68, -93.58),
    ("25025", "25025", "MA", "Suffolk County", 42.33, -71.02),
    ("27053", "27053", "MN", "Hennepin County", 44.90, -93.45),
    ("29095", "29095", "MO", "Jackson County", 39.00, -94.35),
    ("31009", "31009", "NE", "Blaine County", 41.91, -99.98),
    ("31109", "31109", "NE", "Lancaster County", 40.78, -96.69),
    ("36061", "36061", "NY", "New York County", 40.78, -73.97),
    ("36081", "36081", "NY", "Queens County", 40.70, -73.84),
    ("41051", "41051", "OR", "Multnomah County", 45.55, -122.42),
    ("42101", "42101", "PA", "Philadelphia County", 40.01, -75.13),
    ("48029", "48029", "TX", "Bexar County", 29.45, -98.52),
    ("48201", "48201", "TX", "Harris County", 29.86, -95.39),
    ("53033", "53033", "WA", "King County", 47.49, -121.83),
)

# (GHCN id, county FIPS, station display name).  These are listed-station IDs
# and let CI exercise the same identifier convention as production.
_STATIONS = (
    ("USW00094846", "17031", "CHICAGO OHARE INTERNATIONAL AP"),
    ("USW00014922", "27053", "MINNEAPOLIS ST PAUL INTERNATIONAL AP"),
    ("USW00014739", "25025", "BOSTON LOGAN INTERNATIONAL AP"),
)


def generate_fixture(root: Path, *, seed: int = DEFAULT_SEED) -> FixturePaths:
    """Write a reproducible 46-year synthetic donor tree under ``root``.

    The output contains 552 nClimGrid-style monthly CSVs with 37 columns,
    three GHCN access CSVs, and small tabular/map geography inputs.  Existing
    files at these specific fixture paths are replaced deterministically.
    """

    root = Path(root)
    raw, metadata, geography = root / "raw", root / "metadata", root / "geography"
    averages, station_root = raw / "averages", raw / "ghcnd"
    for directory in (averages, station_root, metadata, geography):
        directory.mkdir(parents=True, exist_ok=True)

    dates = np.arange(
        np.datetime64(FIXTURE_START), np.datetime64(FIXTURE_END) + np.timedelta64(1, "D")
    )
    temperatures_f = _synthetic_temperatures(dates, len(_COUNTIES), seed)
    _write_monthly_noaa(averages, dates, temperatures_f)

    counties = metadata / "counties.csv"
    gazetteer = metadata / "gazetteer.csv"
    population = metadata / "population.csv"
    _write_counties(counties)
    _write_gazetteer(gazetteer)
    _write_population(population)
    topojson = geography / "counties.topo.json"
    _write_topojson(topojson)
    station_paths = _write_stations(station_root, dates, temperatures_f)
    _write_manifest(root, seed)
    return FixturePaths(
        root, raw, metadata, geography, counties, gazetteer, population, topojson, station_paths
    )


def _synthetic_temperatures(dates: np.ndarray, n_counties: int, seed: int) -> np.ndarray:
    """Known eight-term mean plus AR(2), seasonal-scale residual process."""

    rng = np.random.default_rng(seed)
    elapsed = (dates - dates[0]).astype("timedelta64[D]").astype(float)
    tau = (elapsed - 8_400.0) / 8_400.0
    phase = 2 * np.pi * elapsed / 365.2425
    county = np.arange(n_counties, dtype=float)
    # Eight terms: intercept, trend, two harmonics, and trend-interacted first harmonic.
    coefficients = np.column_stack(
        (
            54 + 0.7 * (county % 7),
            1.1 + 0.08 * (county % 5),
            20 + 1.3 * (county % 4),
            -4 + 0.9 * (county % 3),
            2.0 * np.sin(county),
            1.5 * np.cos(county),
            0.7 * ((county % 5) - 2),
            0.5 * ((county % 3) - 1),
        )
    )
    design = np.column_stack(
        (
            np.ones(len(dates)),
            tau,
            np.sin(phase),
            np.cos(phase),
            np.sin(2 * phase),
            np.cos(2 * phase),
            tau * np.sin(phase),
            tau * np.cos(phase),
        )
    )
    mean = design @ coefficients.T
    seasonal_sigma = 3.0 + 1.1 * (1 + np.cos(phase))[:, None] / 2
    residual = np.zeros_like(mean)
    common = rng.normal(size=len(dates))
    private = rng.normal(size=mean.shape)
    shock = 0.72 * common[:, None] + np.sqrt(1 - 0.72**2) * private
    for day_index in range(2, len(dates)):
        residual[day_index] = (
            0.54 * residual[day_index - 1]
            - 0.17 * residual[day_index - 2]
            + seasonal_sigma[day_index] * shock[day_index]
        )
    return (mean + residual).astype(np.float32)


def _write_monthly_noaa(averages: Path, dates: np.ndarray, temperatures_f: np.ndarray) -> None:
    celsius = (temperatures_f - 32.0) * (5.0 / 9.0)
    months = np.unique(dates.astype("datetime64[M]"))
    for month in months:
        year_month = str(month)
        year, month_number = (int(part) for part in year_month.split("-"))
        selected = dates.astype("datetime64[M]") == month
        values = celsius[selected]
        target = averages / str(year) / f"tavg-{year}{month_number:02d}-cty-scaled.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            for county_index, (ncei, _, state, name, _, _) in enumerate(_COUNTIES):
                day_values = [f"{value:.2f}" for value in values[:, county_index]]
                day_values.extend(["-999.99"] * (31 - len(day_values)))
                writer.writerow(
                    (
                        "cty",
                        ncei,
                        f"{state}: {name}",
                        year,
                        f"{month_number:02d}",
                        "TAVG",
                        *day_values,
                    )
                )


def _write_counties(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("ncei_code", "fips", "state", "name", "lat", "lon"))
        writer.writerows(_COUNTIES)


def _write_gazetteer(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("GEOID", "NAME", "INTPTLAT", "INTPTLONG"))
        for _, fips, _, name, lat, lon in _COUNTIES:
            writer.writerow((fips, name, f"{lat:.6f}", f"{lon:.6f}"))


def _write_population(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("STATE", "COUNTY", "POPESTIMATE2020"))
        for index, (_, fips, _, _, _, _) in enumerate(_COUNTIES):
            writer.writerow((int(fips[:2]), int(fips[2:]), 25_000 + index * 17_500))


def _write_topojson(path: Path) -> None:
    arcs: list[list[list[float]]] = []
    geometries: list[dict[str, object]] = []
    for arc_index, (_, fips, _, name, lat, lon) in enumerate(_COUNTIES):
        half_width, half_height = 0.12, 0.09
        arcs.append(
            [
                [lon - half_width, lat - half_height],
                [lon + half_width, lat - half_height],
                [lon + half_width, lat + half_height],
                [lon - half_width, lat + half_height],
                [lon - half_width, lat - half_height],
            ]
        )
        geometries.append(
            {
                "type": "Polygon",
                "id": fips,
                "properties": {"name": name},
                "arcs": [[arc_index]],
            }
        )
    payload = {
        "type": "Topology",
        "objects": {"counties": {"type": "GeometryCollection", "geometries": geometries}},
        "arcs": arcs,
    }
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )


def _write_stations(root: Path, dates: np.ndarray, temperatures_f: np.ndarray) -> tuple[Path, ...]:
    county_position = {fips: position for position, (_, fips, *_rest) in enumerate(_COUNTIES)}
    outputs: list[Path] = []
    for station_number, (station_id, county_fips, name) in enumerate(_STATIONS):
        path = root / f"{station_id}.csv"
        outputs.append(path)
        position = county_position[county_fips]
        # A stable, local diurnal spread creates valid integer-F observations.
        tbar = np.rint(temperatures_f[:, position] + station_number - 1).astype(float)
        tmax, tmin = tbar + 9.0, tbar - 9.0
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(
                (
                    "STATION",
                    "DATE",
                    "LATITUDE",
                    "LONGITUDE",
                    "ELEVATION",
                    "NAME",
                    "TMAX",
                    "TMAX_ATTRIBUTES",
                    "TMIN",
                    "TMIN_ATTRIBUTES",
                )
            )
            for index, day in enumerate(dates):
                current = str(day)
                max_value, min_value = tmax[index], tmin[index]
                max_attributes = min_attributes = ",,USW000"
                # Two short interior gaps and a flagged value
                # exercise the production station-QC paths without excluding a month.
                if station_number == 0 and current == "1970-06-10":
                    max_value = min_value = np.nan
                if station_number == 1 and current == "1984-02-18":
                    max_value = min_value = np.nan
                if station_number == 2 and current == "1978-09-09":
                    max_attributes = ",X,USW000"
                max_c = (
                    ""
                    if not np.isfinite(max_value)
                    else str(int(round((max_value - 32) * 5 / 9 * 10)))
                )
                min_c = (
                    ""
                    if not np.isfinite(min_value)
                    else str(int(round((min_value - 32) * 5 / 9 * 10)))
                )
                writer.writerow(
                    (
                        station_id,
                        current,
                        "0",
                        "0",
                        "0",
                        name,
                        max_c,
                        max_attributes,
                        min_c,
                        min_attributes,
                    )
                )
    return tuple(outputs)


def _write_manifest(root: Path, seed: int) -> None:
    payload = {
        "description": "Synthetic test fixture; not observational NOAA data.",
        "end": FIXTURE_END.isoformat(),
        "generator": "weather_basis.validation.fixtures.generate_fixture",
        "n_counties": len(_COUNTIES),
        "n_months": 552,
        "seed": seed,
        "start": FIXTURE_START.isoformat(),
        "stations": [asdict(_station_record(item)) for item in _STATIONS],
    }
    (root / "fixture.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


@dataclass(frozen=True)
class _StationRecord:
    ghcnd_id: str
    county_fips: str
    name: str


def _station_record(values: tuple[str, str, str]) -> _StationRecord:
    return _StationRecord(*values)
