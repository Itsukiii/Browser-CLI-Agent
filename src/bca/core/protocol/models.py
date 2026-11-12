"""Python-first protocol: immutable envelopes with explicitly owned payloads."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from bca.core.errors import ValidationError

from .validation import (
    JsonObject,
    json_object,
    number,
    optional_token,
    positive,
    timestamp,
    token,
)

PROTOCOL_VERSION = 2


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, kw_only=True)
class Model:
    """Common version envelope. Constructors require native Python types."""

    protocol_version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if type(self.protocol_version) is not int or self.protocol_version != PROTOCOL_VERSION:
            raise ValidationError(f"unsupported protocol version: {self.protocol_version}")


class ImageFormat(StrEnum):
    PNG = "png"
    JPEG = "jpeg"


class CoordinateSpace(StrEnum):
    VIEWPORT_CSS = "viewport_css"


@dataclass(frozen=True, kw_only=True)
class Viewport(Model):
    width: float
    height: float
    capture_width: float
    capture_height: float
    device_scale_factor: float = 1.0
    scroll_x: float = 0.0
    scroll_y: float = 0.0
    capture_x: float = 0.0
    capture_y: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        for name in ("width", "height", "capture_width", "capture_height", "device_scale_factor"):
            positive(getattr(self, name), name)
        for name in ("capture_x", "capture_y"):
            number(getattr(self, name), name, minimum=0)
        for name in ("scroll_x", "scroll_y"):
            number(getattr(self, name), name)
        if self.capture_x + self.capture_width > self.width:
            raise ValidationError("capture rectangle exceeds viewport width")
        if self.capture_y + self.capture_height > self.height:
            raise ValidationError("capture rectangle exceeds viewport height")


@dataclass(frozen=True, kw_only=True)
class Frame(Model):
    width: int
    height: int
    data: bytes = field(repr=False)
    format: ImageFormat
    viewport: Viewport
    page_id: str
    frame_id: str = field(default_factory=new_id)
    captured_at: datetime = field(default_factory=utc_now)
    session_id: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        token(self.frame_id, "frame_id")
        token(self.page_id, "page_id")
        optional_token(self.session_id, "session_id")
        timestamp(self.captured_at, "captured_at")
        positive(self.width, "width", integer=True)
        positive(self.height, "height", integer=True)
        if not isinstance(self.viewport, Viewport):
            raise ValidationError("viewport must be a Viewport")
        if not isinstance(self.format, ImageFormat):
            raise ValidationError("format must be ImageFormat")
        if not isinstance(self.data, bytes):
            raise ValidationError("data must be immutable encoded bytes")
        signature = b"\x89PNG\r\n\x1a\n" if self.format is ImageFormat.PNG else b"\xff\xd8\xff"
        if not self.data.startswith(signature):
            raise ValidationError("image bytes do not match the declared signature")

    def pixel_to_css(self, x: float, y: float) -> tuple[float, float]:
        number(x, "x", minimum=0)
        number(y, "y", minimum=0)
        if x >= self.width or y >= self.height:
            raise ValidationError("pixel coordinates outside frame")
        v = self.viewport
        return (
            v.capture_x + x * v.capture_width / self.width,
            v.capture_y + y * v.capture_height / self.height,
        )


class RecognitionStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    ERROR = "error"


@dataclass(frozen=True, kw_only=True)
class ErrorDetail(Model):
    code: str
    message: str
    retryable: bool = False
    details: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        token(self.code, "code")
        if not isinstance(self.message, str) or type(self.retryable) is not bool:
            raise ValidationError("message must be str and retryable must be bool")
        json_object(self.details, "details")


@dataclass(frozen=True, kw_only=True)
class PageState(Model):
    plugin_id: str
    sequence: int
    schema_version: str = "1"
    source_frame_id: str | None = None
    generated_at: datetime = field(default_factory=utc_now)
    data: JsonObject = field(default_factory=dict)
    recognition_status: RecognitionStatus = RecognitionStatus.OK
    diagnostics: tuple[ErrorDetail, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        token(self.plugin_id, "plugin_id")
        token(self.schema_version, "schema_version")
        optional_token(self.source_frame_id, "source_frame_id")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValidationError("sequence must be a nonnegative integer")
        timestamp(self.generated_at, "generated_at")
        json_object(self.data, "data")
        if not isinstance(self.recognition_status, RecognitionStatus):
            raise ValidationError("recognition_status must be RecognitionStatus")
        if not isinstance(self.diagnostics, tuple) or any(
            not isinstance(item, ErrorDetail) for item in self.diagnostics
        ):
            raise ValidationError("diagnostics must be a tuple of ErrorDetail")


@dataclass(frozen=True, kw_only=True)
class Command(Model):
    name: str
    arguments: JsonObject = field(default_factory=dict)
    request_id: str = field(default_factory=new_id)
    source: str = "cli"

    def __post_init__(self) -> None:
        super().__post_init__()
        for name in ("name", "request_id", "source"):
            token(getattr(self, name), name)
        json_object(self.arguments, "arguments")


class ActionType(StrEnum):
    MOUSE_CLICK = "mouse_click"
    MOUSE_MOVE = "mouse_move"
    MOUSE_DOWN = "mouse_down"
    MOUSE_UP = "mouse_up"
    KEY_DOWN = "key_down"
    KEY_UP = "key_up"
    TEXT_INPUT = "text_input"


class MouseButton(StrEnum):
    LEFT = "left"
    MIDDLE = "middle"
    RIGHT = "right"


@dataclass(frozen=True, kw_only=True)
class Action(Model):
    page_id: str
    type: ActionType
    action_id: str = field(default_factory=new_id)
    request_id: str | None = None
    coordinate_space: CoordinateSpace = CoordinateSpace.VIEWPORT_CSS
    x: float | None = None
    y: float | None = None
    button: MouseButton | None = None
    key: str | None = None
    text: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        token(self.action_id, "action_id")
        token(self.page_id, "page_id")
        optional_token(self.request_id, "request_id")
        if not isinstance(self.type, ActionType):
            raise ValidationError("type must be ActionType")
        if not isinstance(self.coordinate_space, CoordinateSpace):
            raise ValidationError("coordinate_space must be CoordinateSpace")
        for name in ("x", "y"):
            value = getattr(self, name)
            if value is not None:
                number(value, name, minimum=0)
        if self.button is not None and not isinstance(self.button, MouseButton):
            raise ValidationError("button must be MouseButton")
        if self.key is not None and (not isinstance(self.key, str) or not self.key):
            raise ValidationError("key must be a nonempty string")
        if self.text is not None and not isinstance(self.text, str):
            raise ValidationError("text must be str")
        if self.type is ActionType.MOUSE_MOVE:
            required = {"x", "y"}
        elif self.type in (ActionType.MOUSE_CLICK, ActionType.MOUSE_DOWN, ActionType.MOUSE_UP):
            required = {"x", "y", "button"}
        elif self.type in (ActionType.KEY_DOWN, ActionType.KEY_UP):
            required = {"key"}
        else:
            required = {"text"}
        supplied = {
            name for name in ("x", "y", "button", "key", "text") if getattr(self, name) is not None
        }
        if supplied != required:
            raise ValidationError(f"{self.type} requires exactly {sorted(required)}")


class ActionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, kw_only=True)
class ActionResult(Model):
    action_id: str
    status: ActionStatus
    started_at: datetime
    finished_at: datetime
    error: ErrorDetail | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        token(self.action_id, "action_id")
        if not isinstance(self.status, ActionStatus):
            raise ValidationError("status must be ActionStatus")
        timestamp(self.started_at, "started_at")
        timestamp(self.finished_at, "finished_at")
        if self.finished_at < self.started_at:
            raise ValidationError("finished_at precedes started_at")
        if self.error is not None and not isinstance(self.error, ErrorDetail):
            raise ValidationError("error must be ErrorDetail")
        if (self.status is ActionStatus.SUCCEEDED) != (self.error is None):
            raise ValidationError("failed/cancelled results require error; success forbids it")


@dataclass(frozen=True, kw_only=True)
class Event(Model):
    type: str
    source: str
    event_id: str = field(default_factory=new_id)
    timestamp: datetime = field(default_factory=utc_now)
    request_id: str | None = None
    data: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        for name in ("type", "source", "event_id"):
            token(getattr(self, name), name)
        optional_token(self.request_id, "request_id")
        timestamp(self.timestamp, "timestamp")
        json_object(self.data, "data")
