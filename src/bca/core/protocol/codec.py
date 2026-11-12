"""Explicit JSON boundary; frames omit their binary payload unless requested."""

import base64
import json
import types
from collections.abc import Callable
from dataclasses import fields
from datetime import datetime
from enum import Enum
from typing import cast, get_args, get_origin, get_type_hints

from bca.core.errors import SerializationError

from .models import Frame, Model
from .validation import JsonObject, JsonValue, json_object


def to_dict(model: Model, *, include_frame_data: bool = False) -> JsonObject:
    """Return detached JSON values; Frame metadata alone cannot recreate a Frame."""
    if not isinstance(model, Model):
        raise SerializationError("expected a protocol Model")

    def encode(value: object) -> JsonValue:
        if isinstance(value, Model):
            value.__post_init__()  # Revalidate mutable payloads at the external boundary.
            return {
                item.name: encode(getattr(value, item.name))
                for item in fields(value)
                if not (isinstance(value, Frame) and item.name == "data" and not include_frame_data)
            }
        if isinstance(value, Enum):
            return encode(value.value)
        if isinstance(value, datetime):
            return value.isoformat(timespec="microseconds")
        if isinstance(value, bytes):
            if not include_frame_data:
                raise SerializationError("binary encoding requires explicit opt-in")
            return base64.urlsafe_b64encode(value).decode("ascii")
        if isinstance(value, dict):
            return {key: encode(child) for key, child in value.items()}
        if isinstance(value, (tuple, list)):
            return [encode(child) for child in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise SerializationError(f"unsupported value: {type(value).__name__}")

    try:
        result = encode(model)
        assert isinstance(result, dict)
        json_object(result, "encoded model")
        return result
    except (ValueError, TypeError, RecursionError) as exc:
        raise SerializationError(str(exc)) from exc


def from_dict[M: Model](model_type: type[M], data: JsonObject) -> M:
    """Decode JSON-compatible values to an explicitly selected model type."""

    def decode(expected: object, value: object) -> object:
        origin = get_origin(expected)
        if origin is types.UnionType:
            if value is None and type(None) in get_args(expected):
                return None
            options = [option for option in get_args(expected) if option is not type(None)]
            if len(options) == 1:
                return decode(options[0], value)
        if origin is tuple:
            if not isinstance(value, list):
                raise SerializationError("tuple fields must be JSON arrays")
            return tuple(decode(get_args(expected)[0], item) for item in value)
        if expected is datetime:
            if not isinstance(value, str):
                raise SerializationError("timestamps must be ISO 8601 strings")
            return datetime.fromisoformat(value)
        if expected is bytes:
            if not isinstance(value, str):
                raise SerializationError("image payload must be Base64 text")
            return base64.b64decode(value, altchars=b"-_", validate=True)
        if isinstance(expected, type) and issubclass(expected, Enum):
            return expected(value)
        if isinstance(expected, type) and issubclass(expected, Model):
            if not isinstance(value, dict):
                raise SerializationError("nested model must be an object")
            return from_dict(expected, value)
        return value  # Scalar and JSON payload constraints are checked by constructors.

    try:
        if not isinstance(model_type, type) or not issubclass(model_type, Model):
            raise SerializationError("model_type must be a Model subclass")
        json_object(data, "data")
        # Detach nested containers from the caller's external representation.
        detached = json.loads(json.dumps(data, allow_nan=False))
        hints = get_type_hints(model_type)
        names = {item.name for item in fields(model_type)}
        if set(detached) - names:
            raise SerializationError(f"unknown fields: {sorted(set(detached) - names)}")
        if "protocol_version" not in detached:
            raise SerializationError("serialized objects require protocol_version")
        # Subclass keyword signatures differ; each dataclass validates its own fields.
        constructor = cast(Callable[..., M], model_type)
        return constructor(**{key: decode(hints[key], value) for key, value in detached.items()})
    except (ValueError, TypeError, RecursionError) as exc:
        raise SerializationError(str(exc)) from exc


def to_json(model: Model, *, include_frame_data: bool = False) -> str:
    return json.dumps(
        to_dict(model, include_frame_data=include_frame_data),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def from_json[M: Model](model_type: type[M], text: str) -> M:
    def pairs(items: list[tuple[str, JsonValue]]) -> JsonObject:
        result: JsonObject = {}
        for key, value in items:
            if key in result:
                raise SerializationError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return from_dict(model_type, json.loads(text, object_pairs_hook=pairs))
    except (ValueError, TypeError, RecursionError) as exc:
        raise SerializationError(str(exc)) from exc
