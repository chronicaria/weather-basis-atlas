"""Canonical, content-addressed identifiers used by the V2 boundaries.

The encoding deliberately accepts only JSON domain values.  In particular,
non-finite floats never acquire an implementation-specific spelling in a
scientific object identifier.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _json_value(value: Any, location: str = "$ ") -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"canonical JSON forbids non-finite float at {location.rstrip()}")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"canonical JSON object key at {location.rstrip()} is not a string")
            normalized[key] = _json_value(item, f"{location}{key}.")
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item, f"{location}{index}.") for index, item in enumerate(value)]
    raise TypeError(
        f"canonical JSON does not support {type(value).__name__} at {location.rstrip()}"
    )


def canonical_json(value: Any) -> str:
    """Return the sole JSON representation permitted in content identities.

    Key order, whitespace, Unicode and non-finite float handling are fixed so
    semantically identical JSON values receive identical IDs on every host.
    """

    return json.dumps(
        _json_value(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def content_id(value: Any, prefix: str = "sha256") -> str:
    """Return ``prefix:<sha256>`` for a canonical JSON value."""

    if not prefix or any(character.isspace() for character in prefix) or ":" in prefix:
        raise ValueError("content ID prefix must be a non-empty token without ':' or whitespace")
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def file_sha256(path: Path) -> str:
    """Hash a regular file without loading it all into memory."""

    candidate = Path(path)
    if not candidate.is_file():
        raise FileNotFoundError(f"cannot hash non-file artifact: {candidate}")
    digest = hashlib.sha256()
    with candidate.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
