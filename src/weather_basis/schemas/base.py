"""V2 strict, immutable domain boundaries; JSON is finite and unknown fields fail."""

from __future__ import annotations

import dataclasses
import math
import re
import types
from typing import Any, Union, get_args, get_origin, get_type_hints

SCHEMA_VERSION = "2.0"
INTERFACE_REVISION = 1


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_fips(value: str) -> str:
    require(
        isinstance(value, str) and re.fullmatch(r"\d{5}", value) is not None,
        "FIPS must be a five-character digit string",
    )
    return value


def _decode(annotation: Any, value: Any, path: str) -> Any:
    origin, args = get_origin(annotation), get_args(annotation)
    if annotation is Any:
        validate_json(value, path)
        return value
    if origin in (Union, types.UnionType):
        for candidate in args:
            try:
                return _decode(candidate, value, path)
            except (ValueError, TypeError):
                pass
        raise ValueError(f"{path}: incompatible value {value!r}")
    if annotation is type(None):
        require(value is None, f"{path}: expected null")
        return None
    if origin in (tuple, list):
        require(isinstance(value, (list, tuple)), f"{path}: expected array")
        if origin is tuple and args and args[-1] is not Ellipsis:
            require(len(value) == len(args), f"{path}: tuple length mismatch")
            decoded = [_decode(t, v, path) for t, v in zip(args, value, strict=True)]
        else:
            decoded = [_decode(args[0], v, path) for v in value]
        return tuple(decoded) if origin is tuple else decoded
    if origin is dict:
        require(isinstance(value, dict), f"{path}: expected object")
        return {
            _decode(args[0], k, path): _decode(args[1], v, f"{path}.{k}") for k, v in value.items()
        }
    if dataclasses.is_dataclass(annotation):
        if isinstance(value, annotation):
            return value
        require(isinstance(value, dict), f"{path}: expected record")
        return annotation.from_dict(value)
    if annotation is float:
        require(
            type(value) in (int, float) and math.isfinite(value), f"{path}: expected finite number"
        )
        return float(value)
    if annotation in (int, str, bool):
        require(type(value) is annotation, f"{path}: expected {annotation.__name__}")
        return value
    raise TypeError(f"{path}: unsupported schema type {annotation}")


def validate_json(value: Any, path: str = "record") -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        require(math.isfinite(value), f"{path}: nonfinite JSON")
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            validate_json(item, f"{path}[{i}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            require(isinstance(key, str), f"{path}: JSON keys must be strings")
            validate_json(item, f"{path}.{key}")
    else:
        raise ValueError(f"{path}: unsupported JSON type {type(value).__name__}")


@dataclasses.dataclass(frozen=True, kw_only=True)
class StrictRecord:
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require(self.schema_version == SCHEMA_VERSION, "Unsupported schema_version")
        hints = get_type_hints(type(self))
        for field in dataclasses.fields(self):
            value = getattr(self, field.name)
            if dataclasses.is_dataclass(value):
                value = dataclasses.asdict(value)
            object.__setattr__(self, field.name, _decode(hints[field.name], value, field.name))

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        require(isinstance(data, dict), f"{cls.__name__}: expected object")
        fields = {f.name for f in dataclasses.fields(cls)}
        require(
            not (data.keys() - fields), f"{cls.__name__}: unknown fields {data.keys() - fields}"
        )
        require(data.get("schema_version") == SCHEMA_VERSION, "Explicit schema_version required")
        hints = get_type_hints(cls)
        try:
            return cls(**{k: _decode(hints[k], v, k) for k, v in data.items()})
        except TypeError as exc:
            raise ValueError(f"{cls.__name__}: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        result = dataclasses.asdict(self)
        validate_json(result)
        return result
