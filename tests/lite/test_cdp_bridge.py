"""Maa callbacks must not block the CDP event loop or replay stale input."""

import asyncio
from io import BytesIO

import pytest
from PIL import Image

np = pytest.importorskip("numpy")

from bca.core.protocol import ActionResult, ActionStatus, Frame, ImageFormat, Viewport
from bca.lite.bridge import BridgeError, CDPBridge


class FakeSession:
    connection = object()
    page_id = "target-one"
    session_id = "session-one"
    generation = 3
    is_ready = True


class FakeCapture:
    available = True
    delay = 0.0

    async def capture(self, page_id: str) -> Frame:
        assert page_id == "target-one"
        await asyncio.sleep(self.delay)
        buf = BytesIO()
        Image.new("RGB", (80, 40), (200, 20, 10)).save(buf, format="PNG")
        return Frame(
            width=80,
            height=40,
            data=buf.getvalue(),
            format=ImageFormat.PNG,
            viewport=Viewport(width=80, height=40, capture_width=80, capture_height=40),
            page_id=page_id,
            session_id="session-one",
        )


class FakeInput:
    available = True

    def __init__(self):
        self.actions = []

    async def execute(self, action):
        self.actions.append(action)
        from datetime import UTC, datetime
        now = datetime.now(UTC)
        return ActionResult(
            action_id=action.action_id,
            status=ActionStatus.SUCCEEDED,
            started_at=now,
            finished_at=now,
        )


def test_screenshot_click_and_no_replay(monkeypatch):
    async def scenario():
        monkeypatch.setattr("bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g"))
        session, capture, input_provider = FakeSession(), FakeCapture(), FakeInput()
        bridge = CDPBridge(loop=asyncio.get_running_loop(), session=session,
                           capture=capture, input_provider=input_provider)
        image = await asyncio.to_thread(bridge.screencap)
        assert image.shape == (40, 80, 3)
        assert np.array_equal(image[0, 0], [10, 20, 200])  # BGR
        assert await asyncio.to_thread(bridge.click, 11, 17)
        assert input_provider.actions[0].x == 11
        assert input_provider.actions[0].y == 17
        assert not await asyncio.to_thread(bridge.click, 11, 17)
        bridge.invalidate()
        assert not bridge.connected
    asyncio.run(scenario())


def test_target_generation_change_rejects_click(monkeypatch):
    async def scenario():
        monkeypatch.setattr("bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g"))
        s, inp = FakeSession(), FakeInput()
        b = CDPBridge(loop=asyncio.get_running_loop(), session=s,
                      capture=FakeCapture(), input_provider=inp)
        await asyncio.to_thread(b.screencap)
        s.generation += 1
        assert not await asyncio.to_thread(b.click, 10, 10)
        assert not inp.actions
    asyncio.run(scenario())


def test_same_target_navigation_fingerprint_rejects_click(monkeypatch):
    async def scenario():
        state = ["g1"]
        async def geometry(_):
            return state[0]
        monkeypatch.setattr("bca.lite.bridge.measure_geometry", geometry)
        inp = FakeInput()
        b = CDPBridge(loop=asyncio.get_running_loop(), session=FakeSession(),
                      capture=FakeCapture(), input_provider=inp)
        await asyncio.to_thread(b.screencap)
        state[0] = "g2"
        assert not await asyncio.to_thread(b.click, 10, 10)
        assert not inp.actions
    asyncio.run(scenario())


def test_timeout_blocks_future_calls(monkeypatch):
    async def scenario():
        monkeypatch.setattr("bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g"))
        capture = FakeCapture()
        capture.delay = 0.3
        b = CDPBridge(loop=asyncio.get_running_loop(), session=FakeSession(),
                      capture=capture, input_provider=FakeInput(), timeout=0.04)
        try:
            await asyncio.to_thread(b.screencap)
        except BridgeError:
            pass
        else:
            raise AssertionError("timeout must reject")
        assert not b.connected
    asyncio.run(scenario())


def test_same_loop_callback_fails_fast(monkeypatch):
    async def scenario():
        monkeypatch.setattr("bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g"))
        b = CDPBridge(loop=asyncio.get_running_loop(), session=FakeSession(),
                      capture=FakeCapture(), input_provider=FakeInput())
        try:
            b.screencap()
        except BridgeError as e:
            assert "event loop" in str(e)
        else:
            raise AssertionError("must refuse same-loop callback")
    asyncio.run(scenario())
