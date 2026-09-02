"""Geography and population inputs for the county atlas.

The functions in this module deliberately keep geography as tabular data.  Map
geometry is rendered in the browser from the vendored TopoJSON; Python only
needs the stable county identifiers, names, internal points, and population.
"""

from __future__ import annotations

import io
import json
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from weather_basis.http import FetchResult, fetch

CONUS_EXCLUDED_PREFIXES: Final[frozenset[str]] = frozenset(
    {"02", "15", "60", "66", "69", "72", "78"}
)
EXPECTED_ATLAS_ONLY: Final[frozenset[str]] = frozenset({"51678"})


class GeographyError(ValueError):
    """Raised when a geography input is malformed or cannot be reconciled."""


@dataclass(frozen=True)
class ReconcileReport:
    """The two-sided county-ID reconciliation used by the atlas build."""

    matched: int
    atlas_only: frozenset[str]
    nclimgrid_only: frozenset[str]
    exceptions_applied: frozenset[str]

    @property
    def ok(self) -> bool:
        """Whether reconciliation has no unexplained differences."""

        return not self.atlas_only and not self.nclimgrid_only


def _fips(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    if not text.isdigit() or len(text) > 5:
        raise GeographyError(f"Invalid county FIPS: {value!r}")
    return text.zfill(5)


def vendor_asset(name: str, url: str, dest: Path) -> FetchResult:
    """Fetch a pinned public geography or web-vendor asset.

    ``name`` is retained in the public API for manifest callers and error
    messages.  It also prevents accidental use of this helper for arbitrary
    downloads: only the Census, NCEI, and jsDelivr hosts used by this project
    are admitted.
    """

    allowed = frozenset({"cdn.jsdelivr.net", "www2.census.gov", "www.ncei.noaa.gov"})
    host = urllib.parse.urlparse(url).hostname
    if host not in allowed:
        raise GeographyError(f"Vendor asset {name!r} has disallowed host: {host!r}")
    return fetch(url, dest, allow_hosts=allowed)


def _read_csv_or_zip(path: Path, *, encoding: str = "utf-8") -> pd.DataFrame:
    """Read a CSV directly or the single county CSV contained in a ZIP."""

    if path.suffix.lower() != ".zip":
        return pd.read_csv(path, dtype="string", encoding=encoding, sep=None, engine="python")
    with zipfile.ZipFile(path) as archive:
        members = [
            member
            for member in archive.namelist()
            if member.lower().endswith(".txt") or member.lower().endswith(".csv")
        ]
        if len(members) != 1:
            raise GeographyError(f"Expected exactly one tabular member in {path}, got {members}")
        with archive.open(members[0]) as source:
            return pd.read_csv(
                io.TextIOWrapper(source, encoding=encoding),
                dtype="string",
                sep=None,
                engine="python",
            )


def load_gazetteer(path: Path) -> pd.DataFrame:
    """Return canonical Census 2020 county names and internal-point centroids."""

    frame = _read_csv_or_zip(path)
    frame.columns = frame.columns.str.strip()
    required = {"GEOID", "NAME", "INTPTLAT", "INTPTLONG"}
    missing = required.difference(frame.columns)
    if missing:
        raise GeographyError(f"Gazetteer missing columns: {', '.join(sorted(missing))}")
    result = frame.loc[:, ["GEOID", "NAME", "INTPTLAT", "INTPTLONG"]].copy()
    result.columns = ["fips", "name", "lat", "lon"]
    result["fips"] = result["fips"].map(_fips)
    result["name"] = result["name"].str.strip()
    result["lat"] = pd.to_numeric(result["lat"], errors="raise")
    result["lon"] = pd.to_numeric(result["lon"], errors="raise")
    if result["fips"].duplicated().any() or result[["name", "lat", "lon"]].isna().any().any():
        raise GeographyError("Gazetteer has duplicate GEOIDs or missing county attributes")
    return result.sort_values("fips", kind="stable").reset_index(drop=True)


def load_population(path: Path) -> pd.DataFrame:
    """Load Census county ``POPESTIMATE2020`` values keyed by five-digit FIPS."""

    frame = _read_csv_or_zip(path, encoding="latin-1")
    required = {"STATE", "COUNTY", "POPESTIMATE2020"}
    missing = required.difference(frame.columns)
    if missing:
        raise GeographyError(f"Population file missing columns: {', '.join(sorted(missing))}")
    state = frame["STATE"].map(_fips).str[-2:]
    county = frame["COUNTY"].map(_fips).str[-3:]
    result = pd.DataFrame(
        {
            "fips": state + county,
            "pop2020": pd.to_numeric(frame["POPESTIMATE2020"], errors="raise"),
        }
    )
    result = result[county != "000"].copy()
    if (result["pop2020"] < 0).any() or result["fips"].duplicated().any():
        raise GeographyError("Population file has negative values or duplicate county FIPS")
    return result.sort_values("fips", kind="stable").reset_index(drop=True)


def geocode_station(lat: float, lon: float) -> tuple[str, bytes]:
    """Resolve a station coordinate to a Census 2020 county and retain raw JSON."""

    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise GeographyError(f"Invalid coordinate ({lat}, {lon})")
    query = urllib.parse.urlencode(
        {
            "x": f"{lon:.8f}",
            "y": f"{lat:.8f}",
            "benchmark": "Public_AR_Current",
            "vintage": "Census2020_Current",
            "format": "json",
        }
    )
    url = f"https://geocoding.geo.census.gov/geocoder/geographies/coordinates?{query}"
    with tempfile.TemporaryDirectory(prefix="wba-geocode-") as temporary:
        response_path = Path(temporary) / "response.json"
        fetch(
            url,
            response_path,
            allow_hosts=frozenset({"geocoding.geo.census.gov"}),
        )
        raw = response_path.read_bytes()
    try:
        payload = json.loads(raw)
        counties = payload["result"]["geographies"]["Counties"]
        county = counties[0]
        fips = _fips(county.get("GEOID") or county.get("GEOID20"))
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise GeographyError("Census geocoder returned no county GEOID") from exc
    return fips, raw


def reconcile_fips(
    nclimgrid_fips: set[str], atlas_ids: set[str], exceptions: pd.DataFrame
) -> ReconcileReport:
    """Reconcile nClimGrid IDs to CONUS map IDs using an explicit whitelist.

    The exceptions table may contain ``atlas_fips``/``fips`` plus an optional
    ``nclimgrid_fips`` column.  An atlas-only exception is removed only when
    it is explicitly listed; no difference is silently tolerated.
    """

    nclim = {_fips(value) for value in nclimgrid_fips}
    atlas = {_fips(value) for value in atlas_ids}
    atlas_conus = {fips for fips in atlas if fips[:2] not in CONUS_EXCLUDED_PREFIXES}
    nclim_conus = {fips for fips in nclim if fips[:2] not in CONUS_EXCLUDED_PREFIXES}

    if exceptions.empty:
        allowed: set[str] = set()
    else:
        column = next(
            (name for name in ("atlas_fips", "fips", "county_fips") if name in exceptions), None
        )
        if column is None:
            raise GeographyError("Exceptions need atlas_fips, fips, or county_fips")
        allowed = {_fips(value) for value in exceptions[column].dropna()}

    raw_atlas_only = atlas_conus - nclim_conus
    raw_nclim_only = nclim_conus - atlas_conus
    applied = raw_atlas_only & allowed
    atlas_only = raw_atlas_only - allowed
    return ReconcileReport(
        matched=len(atlas_conus & nclim_conus),
        atlas_only=frozenset(sorted(atlas_only)),
        nclimgrid_only=frozenset(sorted(raw_nclim_only)),
        exceptions_applied=frozenset(sorted(applied)),
    )
