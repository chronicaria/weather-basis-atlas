"""Deterministic, browser-friendly payloads for the Weather Basis Atlas.

The reader functions deliberately accept the small fixture tables as well as the
full atlas tables.  This keeps the renderer a pure projection of ``results/``:
it never invents a number when an upstream stage has not run.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from weather_basis.io import atomic_write_bytes, gzip_bytes

PAIR_COLUMNS = ("pair", "index_pair", "contract_pair")


def _value(row: pd.Series | dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row and pd.notna(row[name]):
            value = row[name]
            return value.item() if hasattr(value, "item") else value
    return default


def _records(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, dtype={"fips": str, "FIPS": str})


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _round(value: Any, digits: int = 3) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def delta_encode(draws: np.ndarray | list[float], *, scale: int = 1000) -> list[int]:
    """Sort draws, quantise them, then encode first differences losslessly."""

    values = np.sort(np.asarray(draws, dtype=float))
    if values.size == 0:
        return []
    integers = np.rint(values * scale).astype(np.int64)
    return [int(integers[0]), *[int(value) for value in np.diff(integers)]]


def delta_decode(encoded: list[int], *, scale: int = 1000) -> np.ndarray:
    """Decode :func:`delta_encode`; shared with focused payload tests."""

    if not encoded:
        return np.array([], dtype=float)
    return np.cumsum(np.asarray(encoded, dtype=np.int64), dtype=np.int64) / scale


def thin_draws(draws: np.ndarray | list[float], count: int = 1000) -> np.ndarray:
    values = np.sort(np.asarray(draws, dtype=float))
    if len(values) <= count:
        return values
    return values[np.linspace(0, len(values) - 1, count, dtype=int)]


def _pair_name(row: pd.Series) -> str:
    return str(_value(row, *PAIR_COLUMNS, default="unknown"))


def _fips(row: pd.Series) -> str:
    raw = _value(row, "fips", "FIPS", "county_fips", default="")
    return str(raw).split(".")[0].zfill(5)


def _county_rows(root: Path) -> pd.DataFrame:
    for path in (root / "data/metadata/counties.csv", root / "data/counties.csv"):
        rows = _records(path)
        if not rows.empty:
            rows["_fips"] = rows.apply(_fips, axis=1)
            return rows
    return pd.DataFrame(columns=["_fips"])


def _station_rows(root: Path) -> pd.DataFrame:
    for path in (root / "data/metadata/station_registry.csv", root / "data/station_registry.csv"):
        rows = _records(path)
        if not rows.empty:
            return rows
    return pd.DataFrame()


def _stations_payload(rows: pd.DataFrame) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for number, (_, row) in enumerate(rows.iterrows()):
        code = _value(row, "code", "letter", "station_code", default=chr(65 + number))
        output.append(
            {
                "code": str(code),
                "city": _value(row, "city", default=""),
                "station": _value(row, "station", "name", default=""),
                "wban": _value(row, "wban", "WBAN", default=""),
                "ghcn_id": _value(row, "ghcn_id", "ghcnd_id", "id", "GHCN_ID", default=""),
                "lat": _round(_value(row, "lat", "latitude"), 5),
                "lon": _round(_value(row, "lon", "longitude"), 5),
                "listed_from": _value(row, "listed_from", default=None),
                "data_start": _value(row, "data_start", "start", default=None),
                "first_test_season": _value(row, "first_test_season", default=None),
                "short_record": bool(_value(row, "short_record", default=False)),
            }
        )
    return output


def _summary(pairs: pd.DataFrame, county: pd.Series, pair: str) -> dict[str, Any]:
    fips = str(county["_fips"])
    lookup = pairs.attrs.get("by_county_pair", {})
    row = lookup.get((fips, pair), pd.Series(dtype=object))
    return {
        "f": fips,
        "hp": _round(_value(row, "he_pit", "hp")),
        "sp": _value(row, "station_pit", "pit_station", "sp", default=None),
        "hn": _round(_value(row, "he_nearest", "hn")),
        "sn": _value(row, "station_nearest", "nearest_station", "sn", default=None),
        "hb": _round(_value(row, "he_best_pooled", "he_pooled", "hb")),
        "sb": _value(row, "best_pooled", "best_station", "sb", default=None),
        "st": _round(_value(row, "stability", "st")),
        "hd": int(bool(_value(row, "hedgeable", "hd", default=False))),
        "ns": int(bool(_value(row, "no_stable_proxy", "ns", default=False))),
        "n": _value(row, "n_test", "n", default=0),
        "lb": _round(_value(row, "he_pit_lb", "lb")),
        "ub": _round(_value(row, "he_pit_ub", "ub")),
        "c": _value(county, "confidence", "c", default="not_assessed"),
        "rp": int(bool(_value(row, "index_rarely_positive", "rp", default=False))),
        "sk": _round(_value(row, "skill", "sk")),
    }


def _hedge_rows(stations: pd.DataFrame, fips: str, pair: str) -> list[dict[str, Any]]:
    subset = stations.attrs.get("by_county_pair", {}).get((fips, pair), [])
    output = []
    for row in subset:
        output.append(
            {
                "s": _value(row, "station", "station_code", "code", default=""),
                "he": _round(_value(row, "he_pooled", "he")),
                "lb": _round(_value(row, "lb", "he_lb")),
                "ub": _round(_value(row, "ub", "he_ub")),
                "h": _round(_value(row, "h", "h_mean", "hedge_ratio")),
                "rmse": _round(_value(row, "rmse")),
                "es90_upper": _round(_value(row, "es90_upper")),
                "es90_lower": _round(_value(row, "es90_lower")),
                "worst": _round(_value(row, "worst")),
                "worst_season": _value(row, "worst_season", default=None),
                "distance_km": _round(_value(row, "distance_km")),
                "short_record": bool(_value(row, "short_record", default=False)),
            }
        )
    return output


def _draws_for(root: Path, pair: str, fips: str, county_position: int) -> np.ndarray:
    """Find county R2j site draws across the compact and production layouts."""
    base = root / "results/draws/R2j"
    names = (f"{pair}_{fips}_site.npy", f"{fips}_{pair}_site.npy", f"{pair}_site.npy")
    for name in names:
        path = base / name
        if not path.exists():
            continue
        values = np.asarray(np.load(path, allow_pickle=False), dtype=float)
        if values.ndim == 1:
            return values[np.isfinite(values)]
        if values.ndim == 2 and county_position < values.shape[0]:
            return values[county_position][np.isfinite(values[county_position])]
    return np.array([], dtype=float)


def _quotes_for(quotes: pd.DataFrame, pair: str, fips: str) -> list[dict[str, Any]]:
    if quotes.empty:
        return []
    subset = quotes.attrs.get("by_county_pair", {}).get((fips, pair), [])
    output: list[dict[str, Any]] = []
    for row in subset:
        item = {
            "K": _round(_value(row, "K", "strike")),
            "kind": _value(row, "kind", "payoff", default="call"),
            "mid": _round(_value(row, "mid", "expected_payout")),
            "ask": _round(_value(row, "ask")),
            "bid": _round(_value(row, "bid")),
            "bid_raw": _round(_value(row, "bid_raw")),
            "no_bid": bool(_value(row, "no_bid", default=False)),
            "expected_payout": _round(_value(row, "expected_payout", "mid")),
            "residual_load_ask": _round(_value(row, "residual_load_ask")),
            "residual_load_bid": _round(_value(row, "residual_load_bid")),
            "model_load": _round(_value(row, "model_load")),
            "friction": _round(_value(row, "friction")),
            "digital": _round(_value(row, "digital")),
            "station_model": _value(row, "station_model", default=None),
        }
        output.append(item)
    return output


def _rung_for(root: Path, pair: str, county: pd.Series) -> str:
    selection = _selection(root)
    if selection.empty:
        return "R2j (pricing)"
    state = _value(county, "state", "state_abbr", default=None)
    subset = selection[selection.apply(lambda row: _pair_name(row) == pair, axis=1)]
    if state is not None and "state" in subset:
        subset = subset[subset["state"].astype(str) == str(state)]
    if subset.empty:
        return "R2j (pricing)"
    selected = _value(subset.iloc[0], "rung", "selected_rung", "model", default="R2j")
    return f"R2j (pricing); tournament preferred {selected}"


@lru_cache(maxsize=1)
def _selection(root: Path) -> pd.DataFrame:
    return _records(root / "results/tournament/selection.parquet")


def _group_records(frame: pd.DataFrame) -> dict[tuple[str, str], list[pd.Series]]:
    grouped: dict[tuple[str, str], list[pd.Series]] = {}
    for _, row in frame.iterrows():
        grouped.setdefault((_fips(row), _pair_name(row)), []).append(row)
    return grouped


def build_payloads(root: Path, out: Path, config: Any | None = None) -> dict[str, Any]:
    """Write all static JSON payloads, returning sizes for build/check callers."""

    root, out = Path(root), Path(out)
    counties, pairs = _county_rows(root), _records(root / "results/atlas/pairs.parquet")
    stations = _station_rows(root)
    station_atlas = _records(root / "results/atlas/stations.parquet")
    quote_path = root / "results/quotes/quotes.parquet"
    quotes = _records(quote_path if quote_path.exists() else root / "results/quotes.parquet")
    pairs.attrs["by_county_pair"] = {
        key: values[0] for key, values in _group_records(pairs).items()
    }
    station_atlas.attrs["by_county_pair"] = _group_records(station_atlas)
    quotes.attrs["by_county_pair"] = _group_records(quotes)
    site_cfg = config.get("site", {}) if isinstance(config, dict) else getattr(config, "site", {})
    simulate_cfg = (
        config.get("simulate", {}) if isinstance(config, dict) else getattr(config, "simulate", {})
    )
    as_of = str(_cfg(site_cfg, "as_of", ""))
    county_list = []
    for _, row in counties.iterrows():
        county_list.append(
            {
                "fips": row["_fips"],
                "name": _value(row, "name", "county_name", default=""),
                "state": _value(row, "state", "state_abbr", default=""),
                "pop2020": _value(row, "pop2020", "population", default=None),
                "confidence": _value(row, "confidence", default="not_assessed"),
                "centroid": [
                    _round(_value(row, "lon", "longitude"), 5),
                    _round(_value(row, "lat", "latitude"), 5),
                ],
            }
        )
    _write_json(out / "data/counties.json", county_list)
    map_stations = (
        stations.loc[stations["role"].astype(str).str.lower() == "cme"]
        if "role" in stations
        else stations
    )
    _write_json(out / "data/stations.json", _stations_payload(map_stations))
    meta = {
        "as_of": as_of,
        "data_through": _read_data_through(root),
        "model_version": _git_version(root),
        "disclaimer": (
            "Research and education only. Model estimates are not executable quotes, offers, "
            "insurance or advice."
        ),
        "thresholds": {"hedgeable_he": _cfg(site_cfg, "hedgeable_he", None)},
    }
    _write_json(out / "data/meta.json", meta)
    headline = root / "results/atlas/headline.json"
    if headline.exists():
        atomic_write_bytes(out / "data/headline.json", headline.read_bytes())
    pairs_present = sorted({_pair_name(row) for _, row in pairs.iterrows()})
    for pair in pairs_present:
        summary = [_summary(pairs, row, pair) for _, row in counties.iterrows()]
        _write_json(out / f"data/summary/{pair}.json", summary)
    max_size = 0
    for county_position, (_, county) in enumerate(counties.iterrows()):
        fips = str(county["_fips"])
        item = {
            "meta": {
                "fips": fips,
                "name": _value(county, "name", "county_name", default=""),
                "state": _value(county, "state", "state_abbr", default=""),
                "pop": _value(county, "pop2020", "population", default=None),
                "confidence": _value(county, "confidence", default="not_assessed"),
            },
            "pairs": {},
        }
        for pair in pairs_present:
            summary = _summary(pairs, county, pair)
            draws = _draws_for(root, pair, fips, county_position)
            item["pairs"][pair] = {
                "q": [int(value) for value in np.rint(np.quantile(draws, np.linspace(0, 1, 101)))]
                if len(draws)
                else [],
                "d": delta_encode(thin_draws(draws, _cfg(site_cfg, "draws_shipped", 1000))),
                "hedge": _hedge_rows(station_atlas, fips, pair),
                "pit": {
                    "station_pit": summary["sp"],
                    "best_station": summary["sb"],
                    "he_pit": summary["hp"],
                    "he_nearest": summary["hn"],
                    "stability": summary["st"],
                    "lb": summary["lb"],
                    "ub": summary["ub"],
                },
                "oos": [],
                "quotes": _quotes_for(quotes, pair, fips),
                "as_of": as_of,
                "lead_days": int(_cfg(simulate_cfg, "site_lead_in_days", 30)),
                "rung": _rung_for(root, pair, county),
            }
        compressed = gzip_bytes(_json_bytes(item))
        target = out / f"data/county/{fips}.json.gz"
        atomic_write_bytes(target, compressed)
        max_size = max(max_size, len(compressed))
    return {
        "counties": len(counties),
        "pairs": len(pairs_present),
        "county_payload_max_bytes": max_size,
    }


def _write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, _json_bytes(value))


def _cfg(config: Any, key: str, default: Any) -> Any:
    return getattr(config, key, config.get(key, default) if isinstance(config, dict) else default)


def _git_version(root: Path) -> str:
    head = root / ".git/HEAD"
    return head.read_text().strip() if head.exists() else "unknown"


def _read_data_through(root: Path) -> str | None:
    path = root / "results/qc/data_through.json"
    if path.exists():
        try:
            return json.loads(path.read_text()).get("data_through")
        except json.JSONDecodeError:
            return None
    return None
