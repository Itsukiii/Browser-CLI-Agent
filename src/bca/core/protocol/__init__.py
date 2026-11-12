"""Stable, browser-independent data contracts."""

from .codec import from_dict, from_json, to_dict, to_json
from .models import (
    PROTOCOL_VERSION,
    Action,
    ActionResult,
    ActionStatus,
    ActionType,
    Command,
    CoordinateSpace,
    ErrorDetail,
    Event,
    Frame,
    ImageFormat,
    Model,
    MouseButton,
    PageState,
    RecognitionStatus,
    Viewport,
)
from .validation import JsonObject, JsonValue

__all__ = [
    "PROTOCOL_VERSION",
    "JsonObject",
    "JsonValue",
    "from_dict",
    "from_json",
    "to_dict",
    "to_json",
    "Action",
    "ActionResult",
    "ActionStatus",
    "ActionType",
    "Command",
    "CoordinateSpace",
    "ErrorDetail",
    "Event",
    "Frame",
    "ImageFormat",
    "Model",
    "MouseButton",
    "PageState",
    "RecognitionStatus",
    "Viewport",
]
