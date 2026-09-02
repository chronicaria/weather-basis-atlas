"""Configuration loading and deterministic configuration fingerprints."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml


class FrozenDict(Mapping[str, Any]):
    """An immutable mapping which also permits convenient attribute access."""

    def __init__(self, values: Mapping[str, Any]) -> None:
        self._values = MappingProxyType(dict(values))

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __getattr__(self, name: str) -> Any:
        try:
            return self._values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __repr__(self) -> str:
        return f"FrozenDict({dict(self._values)!r})"


@dataclass(frozen=True)
class Config:
    """Immutable project configuration.

    The schema deliberately follows ``defaults.yaml`` rather than duplicating its
    constants in Python.  Top-level and nested keys are available as attributes,
    e.g. ``cfg.hedge.min_train``.
    """

    values: FrozenDict

    def __getattr__(self, name: str) -> Any:
        return getattr(self.values, name)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return FrozenDict({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, FrozenDict):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _merge(base: dict[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[str(key)] = _merge(dict(existing), value)
        else:
            merged[str(key)] = value
    return merged


def load_config(path: Path = Path("config/defaults.yaml"), overrides: dict | None = None) -> Config:
    """Load YAML defaults and recursively apply optional in-memory overrides."""

    with path.open("r", encoding="utf-8") as stream:
        raw = yaml.safe_load(stream)
    if not isinstance(raw, Mapping):
        raise ValueError(f"configuration root must be a mapping: {path}")
    if overrides is not None and not isinstance(overrides, Mapping):
        raise TypeError("overrides must be a mapping")
    merged = _merge(dict(raw), overrides or {})
    return Config(values=_freeze(merged))


def config_hash(cfg: Config) -> str:
    """Return the first 16 hexadecimal characters of canonical YAML's SHA-256."""

    canonical = yaml.safe_dump(
        _thaw(cfg.values), allow_unicode=True, default_flow_style=False, sort_keys=True
    )
    return sha256(canonical.encode("utf-8")).hexdigest()[:16]
