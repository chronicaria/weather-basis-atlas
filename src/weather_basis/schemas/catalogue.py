"""Generate JSON Schema from the authoritative strict dataclass fields."""

from __future__ import annotations

import dataclasses
import types
from typing import Any, Union, get_args, get_origin, get_type_hints

from .base import SCHEMA_VERSION


def _schema(annotation):
    origin, args = get_origin(annotation), get_args(annotation)
    if annotation is Any:
        return {}
    if origin in (Union, types.UnionType):
        return {"anyOf": [_schema(arg) for arg in args]}
    if origin in (tuple, list):
        return {"type": "array", "items": _schema(args[0])}
    if origin is dict:
        return {"type": "object", "additionalProperties": _schema(args[1])}
    if dataclasses.is_dataclass(annotation):
        return json_schema(annotation)
    return {
        "type": {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            type(None): "null",
        }[annotation]
    }


def json_schema(record_type):
    fields = dataclasses.fields(record_type)
    hints = get_type_hints(record_type)
    properties = {field.name: _schema(hints[field.name]) for field in fields}
    properties["schema_version"] = {"const": SCHEMA_VERSION}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "title": record_type.__name__,
        "properties": properties,
        "required": [
            field.name
            for field in fields
            if field.name == "schema_version"
            or (
                field.default is dataclasses.MISSING
                and field.default_factory is dataclasses.MISSING
            )
        ],
        "additionalProperties": False,
    }
