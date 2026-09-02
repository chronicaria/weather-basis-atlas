"""Vendored CME U.S. temperature-station universe (plan Section 5.1)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Station:
    city: str
    station_name: str
    wban: str
    ghcnd_id: str
    icao: str
    lat: float
    lon: float
    elev_m: float
    hdd_code: str
    cdd_code: str
    listed_from: str
    multiplier_usd: float
    base_f: float
    day_rule: str
    settlement_provider: str
    settlement_rule: str
    source_file: str
    source_page: str
    verified_by: str
    verified_on: str


_NUMERIC = {"lat", "lon", "elev_m", "multiplier_usd", "base_f"}
_REQUIRED_COLUMNS = tuple(Station.__dataclass_fields__)


def _default_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "contracts" / "cme_city_universe.csv"


def load_universe(path: Path | None = None) -> tuple[Station, ...]:
    """Load the 13 hand-transcribed listed U.S. CME temperature stations."""
    source = _default_path() if path is None else Path(path)
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or tuple(reader.fieldnames) != _REQUIRED_COLUMNS:
            raise ValueError(f"{source} has unexpected CME universe columns")
        rows = []
        for row in reader:
            if any(row[column] in (None, "") for column in _REQUIRED_COLUMNS):
                raise ValueError(f"{source} contains an empty required field")
            values = {
                column: float(row[column]) if column in _NUMERIC else row[column]
                for column in _REQUIRED_COLUMNS
            }
            rows.append(Station(**values))
    stations = tuple(rows)
    if len(stations) != 13:
        raise ValueError(f"expected 13 CME stations, found {len(stations)}")
    if len({station.ghcnd_id for station in stations}) != len(stations):
        raise ValueError("CME station GHCN identifiers must be unique")
    return stations
