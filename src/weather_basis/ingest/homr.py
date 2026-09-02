"""HOMR station-history retrieval and conservative event extraction.

HOMR response schemas have evolved, so extraction deliberately walks the JSON
and emits only dated location, equipment, and observation-time changes.  The
raw response is the provenance record; this compact table powers the site.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd

_HOMR_SEARCH = "https://www.ncei.noaa.gov/access/homr/services/station/search"
_EVENT_COLUMNS = [
    "ghcnd_id",
    "event_date",
    "event_type",
    "field",
    "old_value",
    "new_value",
    "source_path",
]


def fetch_station(ghcnd_id: str, raw_root: Path):
    """Fetch and cache a HOMR JSON response for a GHCN station identifier."""
    from weather_basis.http import fetch

    station_id = _validate_station_id(ghcnd_id)
    return fetch(
        f"{_HOMR_SEARCH}?qid=GHCND:{station_id}",
        Path(raw_root) / f"{station_id}.json",
        allow_hosts=frozenset({"www.ncei.noaa.gov"}),
    )


def parse_station(path: Path, ghcnd_id: str | None = None) -> pd.DataFrame:
    """Extract dated HOMR location, equipment, and observation-time events.

    Unknown response fields are ignored rather than guessed.  This is
    intentional: the JSON snapshot remains available for any future richer
    interpretation without fabricating historical events.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    station_id = ghcnd_id or _station_id_from_payload(payload) or Path(path).stem
    station_id = _validate_station_id(station_id)
    events: list[dict[str, str]] = []
    for node, node_path in _walk(payload):
        if not isinstance(node, dict):
            continue
        date = _event_date(node)
        if date is None:
            continue
        emitted = False
        for field, value in node.items():
            normalized = _normalize_key(field)
            event_type = _event_type(normalized)
            if event_type is None:
                continue
            old, new = _old_new(value, node)
            if new == "" and old == "":
                continue
            events.append(
                {
                    "ghcnd_id": station_id,
                    "event_date": date,
                    "event_type": event_type,
                    "field": str(field),
                    "old_value": old,
                    "new_value": new,
                    "source_path": node_path,
                }
            )
            emitted = True
        # Some HOMR change records use a generic ``fieldName``/``element``
        # alongside old/new values instead of naming the changed property as
        # a JSON key.  Interpret that label only when it is one of our three
        # deliberately narrow event classes.
        if not emitted:
            for label_key in ("fieldName", "field", "element", "elementName", "changeType", "name"):
                label = node.get(label_key)
                event_type = _event_type(_normalize_key(label))
                if event_type is None:
                    continue
                old, new = _old_new(node.get("newValue", node.get("value", "")), node)
                if old == "" and new == "":
                    continue
                events.append(
                    {
                        "ghcnd_id": station_id,
                        "event_date": date,
                        "event_type": event_type,
                        "field": str(label_key),
                        "old_value": old,
                        "new_value": new,
                        "source_path": node_path,
                    }
                )
                break
    return (
        pd.DataFrame(events, columns=_EVENT_COLUMNS)
        .drop_duplicates()
        .sort_values(["event_date", "event_type", "field"], kind="stable")
        .reset_index(drop=True)
    )


def parse_station_events(path: Path, ghcnd_id: str | None = None) -> pd.DataFrame:
    """Explicit alias used by station-event assembly code."""
    return parse_station(path, ghcnd_id=ghcnd_id)


def _walk(value: Any, path: str = "$") -> Iterator[tuple[Any, str]]:
    yield value, path
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def _event_date(node: dict[str, Any]) -> str | None:
    for key, value in node.items():
        normalized = _normalize_key(key)
        if normalized in {
            "date",
            "changedate",
            "effectivedate",
            "begindate",
            "startdate",
            "validfrom",
        }:
            if isinstance(value, (dict, list, tuple)):
                continue
            parsed = pd.to_datetime(value, errors="coerce")
            if not pd.isna(parsed):
                return parsed.date().isoformat()
    return None


def _event_type(key: str) -> str | None:
    if any(
        token in key for token in ("latitude", "longitude", "elevation", "location", "coordinate")
    ):
        return "location"
    if any(
        token in key for token in ("observationtime", "obstime", "timeofobservation", "timeobs")
    ):
        return "observation_time"
    if any(token in key for token in ("equipment", "instrument", "sensor", "thermometer")):
        return "equipment"
    return None


def _old_new(value: Any, node: dict[str, Any]) -> tuple[str, str]:
    if isinstance(value, dict):
        old = value.get("oldValue", value.get("old", value.get("previous", "")))
        new = value.get("newValue", value.get("new", value.get("current", value.get("value", ""))))
        return _stringify(old), _stringify(new)
    for old_key in ("oldValue", "old", "previous"):
        if old_key in node:
            return _stringify(node[old_key]), _stringify(value)
    return "", _stringify(value)


def _station_id_from_payload(payload: Any) -> str | None:
    for node, _ in _walk(payload):
        if not isinstance(node, dict):
            continue
        for key in ("ghcndId", "ghcnd_id", "id"):
            value = node.get(key)
            if isinstance(value, str) and value.upper().startswith(("US", "CA", "MX")):
                return value
    return None


def _normalize_key(value: Any) -> str:
    return "".join(char.lower() for char in str(value) if char.isalnum())


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def _validate_station_id(ghcnd_id: str) -> str:
    station_id = str(ghcnd_id).strip().upper()
    if not station_id or any(
        char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for char in station_id
    ):
        raise ValueError(f"invalid GHCN station id: {ghcnd_id!r}")
    return station_id
