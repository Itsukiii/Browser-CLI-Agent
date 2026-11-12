"""Small standard-library validators for Python contract boundaries."""

import math
from datetime import datetime

from bca.core.errors import ValidationError

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


def token(value: object, name: str) -> None:
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise ValidationError(f"{name} must be a nonempty token")


def optional_token(value: object, name: str) -> None:
    if value is not None:
        token(value, name)


def number(value: object, name: str, *, minimum: float | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{name} must be a finite number")
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or (minimum is not None and value < minimum):
        raise ValidationError(f"{name} must be finite and >= {minimum}")


def positive(value: object, name: str, *, integer: bool = False) -> None:
    number(value, name, minimum=0)
    if value == 0 or (integer and type(value) is not int):
        raise ValidationError(f"{name} must be a positive {'integer' if integer else 'number'}")


def timestamp(value: object, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"{name} must be a timezone-aware datetime")


def json_object(value: object, name: str) -> None:
    """Check representation, not plugin semantics; reject cycles and nonfinite floats."""
    active: set[int] = set()

    def visit(item: object) -> None:
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float:
            number(item, name)
            return
        if type(item) not in (dict, list):
            raise ValidationError(f"{name} must contain only JSON values")
        if id(item) in active:
            raise ValidationError(f"{name} must not contain cycles")
        active.add(id(item))
        if isinstance(item, dict):
            for key, child in item.items():
                if type(key) is not str:
                    raise ValidationError(f"{name} keys must be strings")
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
        active.remove(id(item))

    if type(value) is not dict:
        raise ValidationError(f"{name} must be a dict")
    visit(value)
