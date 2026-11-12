import asyncio
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from bca.core import errors
from bca.core.plugins import PluginConfig, PluginMetadata
from bca.core.protocol import (
    PROTOCOL_VERSION,
    Action,
    ActionResult,
    ActionStatus,
    ActionType,
    Command,
    ErrorDetail,
    Event,
    Frame,
    ImageFormat,
    MouseButton,
    PageState,
    RecognitionStatus,
    Viewport,
    from_dict,
    from_json,
    to_dict,
    to_json,
)
from bca.core.providers import InputProvider, ProviderLookup, ProviderRegistry


def test_frame_boundary(frame):
    data = to_dict(frame)
    assert "data" not in data
    assert "data" not in json.loads(to_json(frame))
    with pytest.raises(errors.SerializationError):
        from_dict(Frame, data)
    encoded = to_dict(frame, include_frame_data=True)
    assert isinstance(encoded["data"], str)
    assert from_dict(Frame, encoded) == frame
    assert replace(frame, page_id="other").data is frame.data
    jpeg = replace(frame, data=b"\xff\xd8\xff\xe0fixture", format=ImageFormat.JPEG)
    assert from_json(Frame, to_json(jpeg, include_frame_data=True)) == jpeg
    with pytest.raises(errors.ValidationError):
        replace(frame, format=ImageFormat.JPEG)


def test_nonuniform_mapping_and_zoom(frame):
    viewport = Viewport(
        width=800,
        height=600,
        capture_x=100,
        capture_y=50,
        capture_width=400,
        capture_height=100,
        device_scale_factor=2.5,
        scroll_x=-10,
        scroll_y=300,
    )
    changed = replace(frame, width=1000, height=500, viewport=viewport)
    assert changed.pixel_to_css(500, 250) == (300, 100)
    assert changed.pixel_to_css(0, 0) == (100, 50)
    for point in ((1000, 0), (0, 500), (True, 0), (float("inf"), 1)):
        with pytest.raises(errors.ValidationError):
            changed.pixel_to_css(*point)


@pytest.mark.parametrize("kind", list(ActionType))
def test_each_action_rejects_missing_and_extra_parameters(kind):
    if kind is ActionType.MOUSE_MOVE:
        params = {"x": 1, "y": 2}
        extra = {"text": "x"}
    elif kind in (ActionType.MOUSE_CLICK, ActionType.MOUSE_DOWN, ActionType.MOUSE_UP):
        params = {"x": 1, "y": 2, "button": MouseButton.LEFT}
        extra = {"key": "a"}
    elif kind in (ActionType.KEY_DOWN, ActionType.KEY_UP):
        params = {"key": " "}
        extra = {"x": 1}
    else:
        params = {"text": "内容"}
        extra = {"button": MouseButton.LEFT}
    Action(page_id="p", type=kind, **params)
    for field in params:
        with pytest.raises(errors.ValidationError):
            Action(page_id="p", type=kind, **(params | {field: None}))
    with pytest.raises(errors.ValidationError):
        Action(page_id="p", type=kind, **(params | extra))


@pytest.mark.parametrize(
    "factory,changes",
    [
        (
            lambda: Command(name="test"),
            [
                {"name": ""},
                {"source": "has space"},
                {"request_id": 3},
                {"arguments": []},
                {"arguments": {1: "x"}},
                {"arguments": {"x": b"binary"}},
            ],
        ),
        (
            lambda: PageState(plugin_id="p", sequence=0),
            [
                {"plugin_id": ""},
                {"sequence": True},
                {"schema_version": ""},
                {"source_frame_id": ""},
                {"generated_at": "2026-01-01"},
                {"recognition_status": "ok"},
                {"diagnostics": [ErrorDetail(code="x", message="")]},
            ],
        ),
        (
            lambda: Event(type="custom.event", source="p"),
            [
                {"type": ""},
                {"source": 0},
                {"event_id": ""},
                {"request_id": ""},
                {"timestamp": datetime(2026, 1, 1)},
                {"data": {"nan": float("nan")}},
            ],
        ),
        (
            lambda: ErrorDetail(code="x", message=""),
            [
                {"code": ""},
                {"message": None},
                {"retryable": 1},
                {"details": {"x": object()}},
            ],
        ),
    ],
)
def test_lightweight_constraints(factory, changes):
    for change in changes:
        with pytest.raises(errors.ValidationError):
            replace(factory(), **change)


def test_result_constraints():
    now = datetime.now(UTC)
    result = ActionResult(
        action_id="a", status=ActionStatus.SUCCEEDED, started_at=now, finished_at=now
    )
    for change in (
        {"action_id": ""},
        {"status": "succeeded"},
        {"started_at": "now"},
        {"finished_at": datetime(2026, 1, 1)},
        {"error": {}},
        {"finished_at": now - timedelta(seconds=1)},
    ):
        with pytest.raises(errors.ValidationError):
            replace(result, **change)


def test_defaults_ownership_and_codec_snapshot():
    pairs = [
        (Command(name="a"), Command(name="b"), "arguments"),
        (Event(type="x", source="p"), Event(type="x", source="p"), "data"),
        (ErrorDetail(code="x", message=""), ErrorDetail(code="x", message=""), "details"),
        (PluginConfig(), PluginConfig(), "values"),
    ]
    for first, second, attribute in pairs:
        getattr(first, attribute)["x"] = [1]
        assert getattr(second, attribute) == {}
    payload = {"items": [1, {"x": True}]}
    state = PageState(
        plugin_id="p",
        sequence=0,
        data=payload,
        diagnostics=(ErrorDetail(code="vision.partial", message="uncertain"),),
        recognition_status=RecognitionStatus.PARTIAL,
    )
    assert state.data is payload  # Explicit shallow ownership, no automatic deep copy.
    wire = to_dict(state)
    restored = from_dict(PageState, wire)
    payload["items"].append(2)
    assert wire["data"]["items"] == [1, {"x": True}]
    wire["data"]["items"].append(3)
    assert restored.data["items"] == [1, {"x": True}]
    payload["cycle"] = payload
    with pytest.raises(errors.SerializationError):
        to_json(state)


def test_time_and_version():
    time = datetime(2026, 11, 12, 8, 0, 0, 123456, timezone(timedelta(hours=8)))
    event = Event(type="runtime.started", source="runtime", timestamp=time)
    restored = from_json(Event, to_json(event))
    assert restored.timestamp == time
    assert restored.timestamp.microsecond == 123456
    assert restored.timestamp.utcoffset() == timedelta(hours=8)
    assert Event(type="x", source="p").timestamp.tzinfo is UTC
    for value in (1, True, "2", 3):
        with pytest.raises(errors.ValidationError):
            Command(name="x", protocol_version=value)
    assert PROTOCOL_VERSION == 2


@pytest.mark.parametrize(
    "text",
    [
        "null",
        "[]",
        "{",
        '{"name":"x","name":"y"}',
        '{"protocol_version":2,"name":"x","unknown":1}',
        '{"protocol_version":2,"name":"x","arguments":{"x":NaN}}',
        '{"name":"x"}',
    ],
)
def test_invalid_wire(text):
    with pytest.raises(errors.SerializationError):
        from_json(Command, text)


def test_invalid_frame_wire(frame):
    data = to_dict(frame, include_frame_data=True)
    for change in (
        {"data": "!bad!"},
        {"captured_at": 12},
        {"viewport": []},
        {"format": "rgb8"},
        {"width": "2"},
    ):
        with pytest.raises(errors.SerializationError):
            from_dict(Frame, data | change)


def test_plugin_metadata_config_codec():
    metadata = PluginMetadata(plugin_id="p", version="1.0", required_capabilities=("capture",))
    assert from_json(PluginMetadata, to_json(metadata)) == metadata
    config = PluginConfig(values={"nested": [1, True]})
    assert from_dict(PluginConfig, to_dict(config)) == config
    for capabilities in (["capture"], ("",), ("capture", "capture")):
        with pytest.raises(errors.ValidationError):
            replace(metadata, required_capabilities=capabilities)


def test_exception_categories():
    registry: ProviderLookup = ProviderRegistry()
    with pytest.raises(errors.CapabilityNotFoundError):
        registry.get("missing")
    with pytest.raises(errors.ValidationError):
        registry.get(123)
    with pytest.raises(errors.ValidationError):
        registry.get("")
    for cls in (
        errors.ValidationError,
        errors.SerializationError,
        errors.CapabilityNotFoundError,
        errors.CapabilityTypeError,
        errors.ProviderError,
        errors.CommandError,
        errors.PluginError,
        errors.LifecycleError,
        errors.ProviderRegistrationError,
    ):
        assert issubclass(cls, errors.BCAError)
    assert issubclass(errors.ValidationError, ValueError)


def test_input_order_failure_and_cancellation():
    class Inputs(InputProvider):
        available = False

        def __init__(self):
            self.order = []

        async def start(self):
            self.available = True

        async def close(self):
            self.available = False

        async def execute(self, action):
            if not self.available:
                raise errors.CapabilityUnavailableError("closed")
            if action.text == "wait":
                await asyncio.Future()
            self.order.append(action.action_id)
            now = datetime.now(UTC)
            return ActionResult(
                action_id=action.action_id,
                status=ActionStatus.FAILED,
                started_at=now,
                finished_at=now,
                error=ErrorDetail(code="input.rejected", message="fake failure"),
            )

    async def scenario():
        provider = Inputs()
        registry = ProviderRegistry()
        registry.register(provider)
        with pytest.raises(errors.CapabilityUnavailableError) as caught:
            registry.get(InputProvider)
        assert type(caught.value) is errors.CapabilityUnavailableError
        await provider.start()
        for index in range(2):
            action = Action(action_id=str(index), page_id="p", type=ActionType.TEXT_INPUT, text="x")
            result = await provider.execute(action)
            assert result.status is ActionStatus.FAILED
        assert provider.order == ["0", "1"]
        task = asyncio.create_task(
            provider.execute(Action(page_id="p", type=ActionType.TEXT_INPUT, text="wait"))
        )
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert provider.order == ["0", "1"]
        await provider.close()
        await provider.close()
        assert not registry.available("input")

    asyncio.run(scenario())


def test_no_runtime_model_framework_imported():
    assert "pydantic" not in sys.modules
