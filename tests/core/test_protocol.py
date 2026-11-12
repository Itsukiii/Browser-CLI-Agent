from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from bca.core.errors import ValidationError
from bca.core.protocol import (
    Action,
    ActionResult,
    ActionStatus,
    ActionType,
    Command,
    CoordinateSpace,
    ErrorDetail,
    Event,
    ImageFormat,
    MouseButton,
    PageState,
    RecognitionStatus,
    from_dict,
    from_json,
    to_dict,
    to_json,
)


def test_frame_buffer_and_coordinates(frame):
    assert replace(frame).data is frame.data
    assert frame.pixel_to_css(1, 0) == (30, 20)
    assert frame.viewport.scroll_x == 0
    with pytest.raises(FrozenInstanceError):
        frame.width = 4


@pytest.mark.parametrize("point", [(-1, 0), (2, 0), (0, 1), (float("nan"), 0)])
def test_pixel_bounds(frame, point):
    with pytest.raises(ValueError):
        frame.pixel_to_css(*point)


@pytest.mark.parametrize(
    "change",
    [
        {"width": 0},
        {"width": True},
        {"width": "2"},
        {"height": -1},
        {"data": b""},
        {"data": b"123"},
        {"data": bytearray(6)},
        {"format": "bmp"},
        {"page_id": ""},
        {"frame_id": "bad id"},
        {"captured_at": datetime(2026, 1, 1)},
        {"extra": 1},
        {"protocol_version": 1},
    ],
)
def test_invalid_frame(frame, change):
    with pytest.raises((ValidationError, TypeError)):
        replace(frame, **change)


@pytest.mark.parametrize(
    "change",
    [
        {"width": 0},
        {"height": float("inf")},
        {"device_scale_factor": -1},
        {"capture_x": -1},
        {"capture_width": 101},
        {"capture_height": 100},
        {"scroll_y": float("nan")},
    ],
)
def test_invalid_viewport(frame, change):
    with pytest.raises(ValidationError):
        replace(frame.viewport, **change)


def test_all_models_round_trip(frame):
    now = datetime.now(UTC)
    models = [
        frame,
        frame.viewport,
        PageState(plugin_id="test", sequence=0, data={"nested": [1, True, None, {"x": "中"}]}),
        Command(name="click", arguments={"x": 12}),
        Action(page_id="demo", type=ActionType.TEXT_INPUT, text="输入\n"),
        ActionResult(action_id="a", status=ActionStatus.SUCCEEDED, started_at=now, finished_at=now),
        ErrorDetail(code="browser.closed", message="closed"),
        Event(type="custom.dom.changed", source="test", data={"count": 1}),
    ]
    for model in models:
        assert from_json(type(model), to_json(model, include_frame_data=True)) == model
        assert from_dict(type(model), to_dict(model, include_frame_data=True)) == model
    assert "data" not in repr(frame)


@pytest.mark.parametrize(
    "kind,params",
    [
        (ActionType.MOUSE_CLICK, {"x": 0, "y": 10.5, "button": MouseButton.LEFT}),
        (ActionType.MOUSE_MOVE, {"x": 1, "y": 2}),
        (ActionType.MOUSE_DOWN, {"x": 1, "y": 2, "button": MouseButton.RIGHT}),
        (ActionType.MOUSE_UP, {"x": 1, "y": 2, "button": MouseButton.MIDDLE}),
        (ActionType.KEY_DOWN, {"key": "Enter"}),
        (ActionType.KEY_UP, {"key": "Shift"}),
        (ActionType.TEXT_INPUT, {"text": ""}),
    ],
)
def test_action_variants(kind, params):
    action = Action(page_id="demo", type=kind, **params)
    assert from_json(Action, to_json(action)) == action
    assert action.coordinate_space == CoordinateSpace.VIEWPORT_CSS


@pytest.mark.parametrize(
    "change",
    [
        {"x": -1},
        {"x": float("inf")},
        {"y": float("nan")},
        {"x": True},
        {"x": "12"},
        {"x": None},
        {"button": None},
        {"button": "back"},
        {"key": "Enter"},
        {"text": "wrong"},
        {"coordinate_space": "screen"},
        {"type": "scroll"},
    ],
)
def test_invalid_action(change):
    with pytest.raises(ValidationError):
        Action(
            **(
                {
                    "type": ActionType.MOUSE_CLICK,
                    "page_id": "demo",
                    "x": 0,
                    "y": 1,
                    "button": MouseButton.LEFT,
                }
                | change
            )
        )


def test_result_consistency():
    now = datetime.now(UTC)
    base = {"action_id": "a", "started_at": now, "finished_at": now}
    error = ErrorDetail(code="input.failed", message="page closed")
    for status in (ActionStatus.FAILED, ActionStatus.CANCELLED):
        result = ActionResult(**base, status=status, error=error)
        assert from_json(ActionResult, to_json(result)) == result
        with pytest.raises(ValidationError):
            ActionResult(**base, status=status)
    with pytest.raises(ValidationError):
        ActionResult(**base, status=ActionStatus.SUCCEEDED, error=error)
    with pytest.raises(ValidationError):
        ActionResult(
            **(
                base
                | {
                    "status": ActionStatus.SUCCEEDED,
                    "finished_at": now - timedelta(seconds=1),
                }
            )
        )


def test_state_schema_and_defaults():
    first = PageState(plugin_id="p", sequence=0)
    second = PageState(plugin_id="p", sequence=1, recognition_status=RecognitionStatus.UNKNOWN)
    first.data["x"] = 1
    assert second.data == {}
    assert Command(name="a").request_id != Command(name="a").request_id
    for invalid in [{"sequence": -1}, {"data": {"x": object()}}, {"data": {"x": float("nan")}}]:
        with pytest.raises(ValidationError):
            PageState(**({"plugin_id": "p", "sequence": 0} | invalid))
    assert MouseButton.LEFT.value == "left"
    assert ImageFormat.PNG.value == "png"
