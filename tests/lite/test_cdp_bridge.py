"""Maa callbacks must not block the CDP event loop or replay stale input."""

# ruff: noqa: E402 -- optional dependency gate precedes lite imports

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
        monkeypatch.setattr(
            "bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g")
        )
        session, capture, input_provider = FakeSession(), FakeCapture(), FakeInput()
        bridge = CDPBridge(
            loop=asyncio.get_running_loop(),
            session=session,
            capture=capture,
            input_provider=input_provider,
        )
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
        monkeypatch.setattr(
            "bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g")
        )
        s, inp = FakeSession(), FakeInput()
        b = CDPBridge(
            loop=asyncio.get_running_loop(), session=s, capture=FakeCapture(), input_provider=inp
        )
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
        b = CDPBridge(
            loop=asyncio.get_running_loop(),
            session=FakeSession(),
            capture=FakeCapture(),
            input_provider=inp,
        )
        await asyncio.to_thread(b.screencap)
        state[0] = "g2"
        assert not await asyncio.to_thread(b.click, 10, 10)
        assert not inp.actions

    asyncio.run(scenario())


def test_timeout_blocks_future_calls(monkeypatch):
    async def scenario():
        monkeypatch.setattr(
            "bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g")
        )
        capture = FakeCapture()
        capture.delay = 0.3
        b = CDPBridge(
            loop=asyncio.get_running_loop(),
            session=FakeSession(),
            capture=capture,
            input_provider=FakeInput(),
            timeout=0.04,
        )
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
        monkeypatch.setattr(
            "bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g")
        )
        b = CDPBridge(
            loop=asyncio.get_running_loop(),
            session=FakeSession(),
            capture=FakeCapture(),
            input_provider=FakeInput(),
        )
        try:
            b.screencap()
        except BridgeError as e:
            assert "event loop" in str(e)
        else:
            raise AssertionError("must refuse same-loop callback")

    asyncio.run(scenario())


def test_invalidate_during_capture_never_waits_on_worker_lock(monkeypatch):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class Capture(FakeCapture):
            async def capture(self, page):
                entered.set()
                await release.wait()
                return await super().capture(page)

        monkeypatch.setattr(
            "bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g")
        )
        b = CDPBridge(
            loop=asyncio.get_running_loop(),
            session=FakeSession(),
            capture=Capture(),
            input_provider=FakeInput(),
        )
        worker = asyncio.create_task(asyncio.to_thread(b.screencap))
        await entered.wait()
        # Same-loop rejection while another call is pending must be immediate.
        with pytest.raises(BridgeError, match="event loop"):
            b.screencap()
        b.invalidate()
        closing = asyncio.create_task(b.aclose())
        await asyncio.sleep(0)
        assert not closing.done()
        release.set()
        with pytest.raises(BridgeError):
            await worker
        await closing
        assert b.observation is None

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["generation", "stop", "age"])
def test_recheck_after_geometry_await(monkeypatch, change):
    async def scenario():
        s, inp = FakeSession(), FakeInput()
        b = CDPBridge(
            loop=asyncio.get_running_loop(),
            session=s,
            capture=FakeCapture(),
            input_provider=inp,
            max_frame_age=0.05,
        )
        monkeypatch.setattr(
            "bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g")
        )
        await asyncio.to_thread(b.screencap)

        async def geometry(_):
            if change == "generation":
                s.generation += 1
            elif change == "stop":
                b.invalidate()
            else:
                await asyncio.sleep(0.07)
            return "g"

        monkeypatch.setattr("bca.lite.bridge.measure_geometry", geometry)
        assert not await asyncio.to_thread(b.click, 10, 10)
        assert not inp.actions
        await b.aclose()

    asyncio.run(scenario())


def test_rebind_cannot_be_reauthorized_by_new_capture(monkeypatch):
    async def scenario():
        monkeypatch.setattr(
            "bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g")
        )
        s = FakeSession()
        b = CDPBridge(
            loop=asyncio.get_running_loop(),
            session=s,
            capture=FakeCapture(),
            input_provider=FakeInput(),
        )
        await asyncio.to_thread(b.screencap)
        s.generation += 1
        with pytest.raises(BridgeError):
            await asyncio.to_thread(b.screencap)
        assert not b.connected
        await b.aclose()

    asyncio.run(scenario())


def test_timeout_drain_waits_for_actual_coroutine_cleanup(monkeypatch):
    async def scenario():
        cleanup_entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Capture(FakeCapture):
            async def capture(self, page):
                try:
                    await asyncio.sleep(5)
                finally:
                    cleanup_entered.set()
                    await release.wait()
                    finished.set()

        monkeypatch.setattr(
            "bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g")
        )
        b = CDPBridge(
            loop=asyncio.get_running_loop(),
            session=FakeSession(),
            capture=Capture(),
            input_provider=FakeInput(),
            timeout=0.03,
        )
        with pytest.raises(BridgeError, match="timed out"):
            await asyncio.to_thread(b.screencap)
        await cleanup_entered.wait()
        close = asyncio.create_task(b.aclose())
        await asyncio.sleep(0)
        assert not close.done()
        release.set()
        await close
        assert finished.is_set()

    asyncio.run(scenario())


def test_unconfirmed_input_blocks_even_after_new_capture(monkeypatch):
    async def scenario():
        class Input(FakeInput):
            async def execute(self, action):
                from dataclasses import replace

                return replace(await super().execute(action), status=ActionStatus.FAILED)

        monkeypatch.setattr(
            "bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g")
        )
        inp = Input()
        b = CDPBridge(
            loop=asyncio.get_running_loop(),
            session=FakeSession(),
            capture=FakeCapture(),
            input_provider=inp,
        )
        await asyncio.to_thread(b.screencap)
        assert not await asyncio.to_thread(b.click, 10, 10)
        assert b.input_outcome == "unknown"
        with pytest.raises(BridgeError):
            await asyncio.to_thread(b.screencap)
        assert len(inp.actions) == 1
        await b.aclose()

    asyncio.run(scenario())


def test_cancel_native_worker_waits_and_revokes_entry(monkeypatch):
    import threading

    from bca.lite.bridge import run_native

    async def scenario():
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        b = CDPBridge(
            loop=asyncio.get_running_loop(),
            session=FakeSession(),
            capture=FakeCapture(),
            input_provider=FakeInput(),
        )

        def work():
            entered.set()
            release.wait(2)
            assert not b.click(1, 1)
            finished.set()

        task = asyncio.create_task(run_native(b, work))
        await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0.01)
        task.cancel()
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
        await b.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("x,y", [(-1, 0), (80, 0), (0, 40), (True, 1), (1.5, 1)])
def test_invalid_coordinates_never_dispatch(monkeypatch, x, y):
    async def scenario():
        monkeypatch.setattr(
            "bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g")
        )
        inp = FakeInput()
        b = CDPBridge(
            loop=asyncio.get_running_loop(),
            session=FakeSession(),
            capture=FakeCapture(),
            input_provider=inp,
        )
        await asyncio.to_thread(b.screencap)
        assert not await asyncio.to_thread(b.click, x, y)
        assert not inp.actions
        await b.aclose()

    asyncio.run(scenario())


def test_explicit_observation_authorization_is_one_shot_and_exact(monkeypatch):
    from dataclasses import replace

    async def scenario():
        monkeypatch.setattr(
            "bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g")
        )
        inp = FakeInput()
        b = CDPBridge(
            loop=asyncio.get_running_loop(),
            session=FakeSession(),
            capture=FakeCapture(),
            input_provider=inp,
            require_authorization=True,
        )
        await asyncio.to_thread(b.screencap)
        old = b.observation
        with pytest.raises(BridgeError, match="obsolete"):
            await b.authorize(replace(old))
        assert not await asyncio.to_thread(b.click, 10, 10)
        await asyncio.to_thread(b.screencap)
        with pytest.raises(BridgeError, match="obsolete"):
            await b.authorize(old)
        current = b.observation
        await b.authorize(current)
        assert await asyncio.to_thread(b.click, 10, 10)
        assert not await asyncio.to_thread(b.click, 10, 10)
        # A second step needs an actual new capture and a new exact reference.
        await asyncio.to_thread(b.screencap)
        await b.authorize(b.observation)
        assert await asyncio.to_thread(b.click, 12, 12)
        assert len(inp.actions) == 2
        await b.aclose()

    asyncio.run(scenario())
