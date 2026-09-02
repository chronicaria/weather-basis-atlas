"""NOAA nClimGrid-Daily county-file ingestion (plan Sections 4.3--4.4)."""
from __future__ import annotations

import calendar
import csv
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from weather_basis.http import FetchResult, fetch
from weather_basis.io import sha256

BASE_URL = "https://www.ncei.noaa.gov/data/nclimgrid-daily/access/averages"
MISSING = -999.99
VARIABLES = frozenset({"tavg", "tmax", "tmin", "prcp"})


class NClimGridError(ValueError):
    """A county source file did not meet the nClimGrid monthly-file contract."""


@dataclass(frozen=True, order=True)
class Month:
    year: int
    month: int

    def __post_init__(self) -> None:
        if self.year < 1 or self.month not in range(1, 13):
            raise ValueError(f"Invalid month: {self.year}-{self.month}")

    @classmethod
    def parse(cls, value: str) -> Month:
        try:
            year_text, month_text = value.split("-", 1)
            return cls(int(year_text), int(month_text))
        except (AttributeError, ValueError) as exc:
            raise ValueError(f"Use YYYY-MM, not {value!r}.") from exc

    @property
    def compact(self) -> str:
        return f"{self.year:04d}{self.month:02d}"

    def previous(self) -> Month:
        """Return the preceding calendar month."""
        return Month(self.year - 1, 12) if self.month == 1 else Month(self.year, self.month - 1)

    def next(self) -> Month:
        """Return the following calendar month."""
        return Month(self.year + 1, 1) if self.month == 12 else Month(self.year, self.month + 1)

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


@dataclass(frozen=True)
class County:
    ncei_code: str
    fips: str
    state_fips: str
    state_abbr: str
    name: str


@dataclass(frozen=True)
class VerifyReport:
    files_checked: int
    drift: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.drift


def source_name(variable: str, month: Month, status: str = "scaled") -> str:
    _validate_source_args(variable, status)
    return f"{variable}-{month.compact}-cty-{status}.csv"


def source_url(variable: str, month: Month, status: str = "scaled") -> str:
    return f"{BASE_URL}/{month.year}/{source_name(variable, month, status)}"


def fetch_month(
    variable: str, month: Month, raw_root: Path, *, status: str = "scaled"
) -> FetchResult:
    """Fetch one county file through the project HTTP allowlist."""
    _validate_source_args(variable, status)
    destination = raw_root / "averages" / str(month.year) / source_name(variable, month, status)
    return fetch(
        source_url(variable, month, status),
        destination,
        allow_hosts=frozenset({"www.ncei.noaa.gov"}),
    )


def parse_month(
    path: Path, variable: str, month: Month, state_codes: Mapping[str, str]
) -> tuple[np.ndarray, list[County]]:
    """Parse headerless NOAA data into Celsius ``(days, counties)`` float32 values."""
    _validate_source_args(variable, "scaled")
    days = calendar.monthrange(month.year, month.month)[1]
    seen: dict[str, tuple[County, np.ndarray]] = {}
    with path.open(encoding="utf-8", newline="") as source:
        for line_number, row in enumerate(csv.reader(source), start=1):
            if len(row) != 37:
                raise NClimGridError(f"{path}:{line_number} has {len(row)} columns, not 37")
            region, code, label, year, raw_month, element = (item.strip() for item in row[:6])
            expected = (str(month.year), f"{month.month:02d}", variable.upper())
            if region != "cty" or (year, raw_month, element) != expected:
                raise NClimGridError(f"{path}:{line_number} has unexpected identifiers")
            if code in seen:
                raise NClimGridError(f"{path}:{line_number} repeats NCEI county {code}")
            county = _county_from_row(code, label, state_codes)
            try:
                values = np.asarray([float(value) for value in row[6 : 6 + days]])
            except ValueError as exc:
                raise NClimGridError(f"{path}:{line_number} has an invalid value") from exc
            values[values <= MISSING] = np.nan
            seen[code] = (county, values)
    if not seen:
        raise NClimGridError(f"{path} contains no county rows")
    ordered = sorted(seen.values(), key=lambda pair: pair[0].fips)
    counties = [county for county, _ in ordered]
    if len({county.fips for county in counties}) != len(counties):
        raise NClimGridError(f"{path} maps multiple NCEI counties to one FIPS")
    return np.column_stack([values for _, values in ordered]).astype(np.float32), counties


def verify_manifest(manifest_csv: Path, raw_root: Path) -> VerifyReport:
    """Recompute all raw and version SHA-256 digests named by a manifest."""
    with manifest_csv.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    needed = {"local_path", "sha256", "version_local_path", "version_sha256"}
    if not rows or not needed.issubset(rows[0]):
        raise NClimGridError(f"{manifest_csv} lacks nClimGrid manifest columns")
    drift: list[str] = []
    checked = 0
    for row in rows:
        for path_key, hash_key in (
            ("local_path", "sha256"),
            ("version_local_path", "version_sha256"),
        ):
            candidate = _manifest_path(raw_root, row[path_key])
            checked += 1
            if not candidate.is_file():
                drift.append(f"missing {row[path_key]}")
            elif sha256(candidate) != row[hash_key]:
                drift.append(f"sha256 {row[path_key]}")
    return VerifyReport(checked, tuple(drift))


def _validate_source_args(variable: str, status: str) -> None:
    if variable not in VARIABLES:
        raise ValueError(f"Unsupported nClimGrid variable: {variable!r}")
    if status not in {"scaled", "prelim"}:
        raise ValueError(f"Unsupported nClimGrid status: {status!r}")


def _county_from_row(code: str, label: str, state_codes: Mapping[str, str]) -> County:
    if len(code) != 5 or not code.isdigit():
        raise NClimGridError(f"Invalid NCEI county code: {code!r}")
    state_abbr, delimiter, name = label.partition(":")
    if not delimiter:
        raise NClimGridError(f"Unexpected county label: {label!r}")
    try:
        state_fips = str(state_codes[code[:2]]).zfill(2)
    except KeyError as exc:
        raise NClimGridError(f"No state crosswalk for NCEI county {code}") from exc
    if code == "18511":
        return County(code, "11001", "11", "DC", "District of Columbia")
    return County(code, f"{state_fips}{code[2:]}", state_fips, state_abbr.strip(), name.strip())


def _manifest_path(raw_root: Path, local_path: str) -> Path:
    relative = Path(local_path)
    candidates = raw_root / relative, raw_root.parent / relative, raw_root.parent.parent / relative
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return raw_root / relative
