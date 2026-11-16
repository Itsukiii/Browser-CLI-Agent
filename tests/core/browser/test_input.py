import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from bca.core.browser import BrowserInputProvider, BrowserSession, TargetLostError
from bca.core.errors import CapabilityUnavailableError, LifecycleError, ValidationError
from bca.core.protocol import Action, ActionStatus, to_json
from bca.core.protocol import ActionType as A
from bca.core.protocol import MouseButton as B
from bca.core.providers import InputProvider, ProviderRegistry

from .test_capture import CapturePeer


class InputPeer(CapturePeer):
    def __init__(self):
        super().__init__()
        self.hold_type = None
        self.reject_type = None
        self.input_gate = asyncio.Event()
        self.input_gate.set()
        self.before_response = None

    @property
    def inputs(self):
        return [r for r in self.requests if r["method"].startswith("Input.")]

    async def _reply(self, socket, request):
        if request["method"].startswith("Input."):
            kind = request["params"].get("type", "text")
            if kind == self.hold_type:
                await self.input_gate.wait()
            if self.before_response:
                await self.before_response(request)
            if kind == self.reject_type:
                await socket.send(
                    json.dumps(
                        {
                            "id": request["id"],
                            "sessionId": request["sessionId"],
                            "error": {"code": -32000, "message": "private data"},
                        }
                    )
                )
                return
        await super()._reply(socket, request)


def action(kind=A.MOUSE_CLICK, **kwargs):
    if kind in (A.MOUSE_CLICK, A.MOUSE_DOWN, A.MOUSE_UP, A.MOUSE_MOVE):
        kwargs = {"x": 12.25, "y": 23.75, **kwargs}
        if kind != A.MOUSE_MOVE:
            kwargs.setdefault("button", B.LEFT)
    return Action(page_id=kwargs.pop("page_id", "page-a"), type=kind, **kwargs)


async def ready(peer, **kwargs):
    session = BrowserSession(peer.endpoint)
    await session.connect()
    await session.bind("page-a")
    provider = BrowserInputProvider(session, **kwargs)
    await provider.start()
    return session, provider


@pytest.mark.parametrize("button,mask", [(B.LEFT, 1), (B.RIGHT, 2), (B.MIDDLE, 4)])
def test_mouse_order_masks_and_decimal_coordinates(button, mask):
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer)
            for kind in (A.MOUSE_MOVE, A.MOUSE_DOWN, A.MOUSE_MOVE, A.MOUSE_UP, A.MOUSE_CLICK):
                a = action(kind, **({} if kind == A.MOUSE_MOVE else {"button": button}))
                r = await p.execute(a)
                assert r.action_id == a.action_id and r.status is ActionStatus.SUCCEEDED
                assert r.started_at.tzinfo is UTC and r.finished_at >= r.started_at
                to_json(r)
            params = [r["params"] for r in peer.inputs]
            assert [r["type"] for r in params] == [
                "mouseMoved",
                "mousePressed",
                "mouseMoved",
                "mouseReleased",
                "mousePressed",
                "mouseReleased",
            ]
            assert [r["buttons"] for r in params] == [0, mask, mask, 0, mask, 0]
            assert [r["clickCount"] for r in params] == [0, 1, 0, 1, 1, 1]
            assert all(r["x"] == 12.25 and r["y"] == 23.75 for r in params)
            await p.close()
            assert s.is_ready
            await s.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "key,code,vk,text",
    [
        ("a", "KeyA", 65, "a"),
        ("Z", "KeyZ", 90, "Z"),
        ("5", "Digit5", 53, "5"),
        (" ", "Space", 32, " "),
        ("Enter", "Enter", 13, "\r"),
        ("Tab", "Tab", 9, ""),
        ("Escape", "Escape", 27, ""),
        ("Backspace", "Backspace", 8, ""),
        ("Delete", "Delete", 46, ""),
        ("ArrowLeft", "ArrowLeft", 37, ""),
        ("ArrowUp", "ArrowUp", 38, ""),
        ("ArrowRight", "ArrowRight", 39, ""),
        ("ArrowDown", "ArrowDown", 40, ""),
        ("Home", "Home", 36, ""),
        ("End", "End", 35, ""),
        ("PageUp", "PageUp", 33, ""),
        ("PageDown", "PageDown", 34, ""),
    ],
)
def test_keys(key, code, vk, text):
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer)
            for kind in (A.KEY_DOWN, A.KEY_UP):
                assert (await p.execute(action(kind, key=key))).status is ActionStatus.SUCCEEDED
            down, up = [r["params"] for r in peer.inputs]
            assert (down["key"], down["code"], down["windowsVirtualKeyCode"], down["text"]) == (
                key,
                code,
                vk,
                text,
            )
            assert down["type"] == ("keyDown" if text else "rawKeyDown")
            assert up["type"] == "keyUp" and up["text"] == ""
            await p.close()
            await s.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "modifier,bit,letter", [("Shift", 8, "A"), ("Ctrl", 2, "a"), ("Alt", 1, "a"), ("Meta", 4, "a")]
)
def test_modifiers_repeats_and_mouse_flags(modifier, bit, letter):
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer)
            await p.execute(action(A.KEY_DOWN, key=modifier))
            await p.execute(action(A.KEY_DOWN, key="a"))
            await p.execute(action(A.KEY_DOWN, key="a"))
            await p.execute(action(A.MOUSE_MOVE))
            await p.execute(action(A.KEY_UP, key="a"))
            await p.execute(action(A.KEY_UP, key=modifier))
            params = [r["params"] for r in peer.inputs]
            assert [r["modifiers"] for r in params] == [bit] * 5 + [0]
            assert params[1]["key"] == letter
            assert params[1]["text"] == ("A" if modifier == "Shift" else "")
            assert params[2]["autoRepeat"] is True
            assert params[4]["key"] == letter
            await p.close()
            await s.close()

    asyncio.run(scenario())


def test_unicode_empty_and_registry_lifecycle():
    async def scenario():
        async with InputPeer() as peer:
            s = BrowserSession(peer.endpoint)
            p = BrowserInputProvider(s)
            registry = ProviderRegistry()
            registry.register(p)
            assert not registry.available(InputProvider)
            with pytest.raises(CapabilityUnavailableError):
                await p.start()
            await s.connect()
            await s.bind("page-a")
            await p.start()
            await p.start()
            assert registry.get(InputProvider) is p
            a = action(A.TEXT_INPUT, text="")
            assert (await p.execute(a)).status is ActionStatus.SUCCEEDED
            assert not peer.inputs
            assert (await p.execute(action(A.TEXT_INPUT, text="中文 日本語 😀"))).error is None
            assert peer.inputs[0]["params"] == {"text": "中文 日本語 😀"}
            await p.close()
            await p.close()
            assert s.is_ready
            with pytest.raises(LifecycleError):
                await p.start()
            with pytest.raises(CapabilityUnavailableError):
                await p.execute(a)
            await s.close()
            assert s.connection.pending_count == 0 and not s.connection.reader_running

    asyncio.run(scenario())


@pytest.mark.parametrize("kwargs", [{"x": 100}, {"y": 50}, {"page_id": "page-b"}, {"x": 100.01}])
def test_invalid_mouse(kwargs):
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer)
            with pytest.raises(ValidationError):
                await p.execute(action(**kwargs))
            assert not peer.inputs
            await p.close()
            await s.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("key", ["Unknown", "中文", "ab", "F100"])
def test_unsupported_key_is_validation(key):
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer)
            with pytest.raises(ValidationError):
                await p.execute(action(A.KEY_DOWN, key=key))
            assert not peer.inputs
            await p.close()
            await s.close()

    asyncio.run(scenario())


def test_hold_contract_and_close_releases():
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer)
            with pytest.raises(ValidationError):
                await p.execute(action(A.MOUSE_UP))
            with pytest.raises(ValidationError):
                await p.execute(action(A.KEY_UP, key="a"))
            await p.execute(action(A.MOUSE_DOWN))
            for kind in (A.MOUSE_DOWN, A.MOUSE_CLICK):
                with pytest.raises(ValidationError):
                    await p.execute(action(kind))
            await p.execute(action(A.MOUSE_DOWN, button=B.RIGHT))
            assert peer.inputs[-1]["params"]["buttons"] == 3
            await p.execute(action(A.KEY_DOWN, key="Shift"))
            await p.execute(action(A.KEY_DOWN, key="a"))
            await p.close()
            released = [r["params"] for r in peer.inputs[-4:]]
            assert [r["type"] for r in released] == [
                "keyUp",
                "keyUp",
                "mouseReleased",
                "mouseReleased",
            ]
            assert released[0]["key"] == "A" and released[1]["key"] == "Shift"
            assert released[-1]["buttons"] == 0
            assert s.is_ready
            await s.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["timeout", "cancel", "reject"])
def test_partial_click_cleanup_and_uncertainty(failure):
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer, timeout=0.1)
            peer.hold_type = "mousePressed"
            if failure == "reject":
                peer.reject_type = "mouseReleased"
            else:
                peer.input_gate.clear()
            task = asyncio.create_task(p.execute(action()))
            await peer.seen("Input.dispatchMouseEvent")
            if failure == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert p.last_error.code == "browser.cancelled"
            else:
                r = await task
                assert r.status is ActionStatus.FAILED
                assert r.error.code == (
                    "browser.timeout" if failure == "timeout" else "browser.command"
                )
                assert "private data" not in to_json(r)
                if failure == "reject":
                    assert r.error.details["completed_steps"] == 1
            assert p.input_state_uncertain
            assert any(r["params"]["type"] == "mouseReleased" for r in peer.inputs)
            assert s.connection.pending_count == 0
            peer.input_gate.set()
            peer.reject_type = None
            await p.close()
            await s.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "operation", ["switch", "rebind", "unbind", "destroy", "disconnect", "close", "provider_close"]
)
def test_inflight_binding_loss_never_routes_release_to_new_target(operation):
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer)
            old_sid = s.session_id
            peer.hold_type = "mousePressed"
            peer.input_gate.clear()
            task = asyncio.create_task(p.execute(action()))
            await peer.seen("Input.dispatchMouseEvent")
            closing = None
            if operation == "switch":
                await s.bind("page-b")
            elif operation == "rebind":
                await s.unbind()
                await s.bind("page-a")
            elif operation == "unbind":
                await s.unbind()
            elif operation == "destroy":
                await peer.emit("Target.targetDestroyed", {"targetId": "page-a"})
            elif operation == "disconnect":
                for socket in tuple(peer.connections):
                    await socket.close()
            elif operation == "provider_close":
                closing = asyncio.create_task(p.close())
                await asyncio.sleep(0)
            else:
                await s.close()
            peer.input_gate.set()
            with pytest.raises(TargetLostError):
                await task
            if closing:
                await closing
            assert all(r["sessionId"] == old_sid for r in peer.inputs)
            assert p.last_error is not None
            await p.close()
            await s.close()

    asyncio.run(scenario())


def test_serial_execution_and_cancelled_waiter_do_not_release_other_call():
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer)
            peer.hold_type = "mousePressed"
            peer.input_gate.clear()
            first = asyncio.create_task(p.execute(action()))
            await peer.seen("Input.dispatchMouseEvent")
            second = asyncio.create_task(p.execute(action()))
            third = asyncio.create_task(p.execute(action()))
            await asyncio.sleep(0)
            second.cancel()
            with pytest.raises(asyncio.CancelledError):
                await second
            assert len(peer.inputs) == 1
            peer.input_gate.set()
            assert (await first).error is None and (await third).error is None
            assert [r["params"]["type"] for r in peer.inputs] == [
                "mousePressed",
                "mouseReleased",
            ] * 2
            await p.close()
            await s.close()

    asyncio.run(scenario())


def test_lock_timeout_without_side_effects():
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer, timeout=0.03)
            await p._lock.acquire()
            try:
                r = await p.execute(action())
                assert r.error.code == "browser.timeout"
                assert r.error.details["stage"] == "lock"
                assert not peer.inputs and not p.input_state_uncertain
            finally:
                p._lock.release()
            await p.close()
            await s.close()

    asyncio.run(scenario())


def test_current_geometry_intersection_and_resize():
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer)
            peer.layout = dict(peer.visual, clientWidth=80.5)
            assert (await p.execute(action(x=80.25))).error is None
            with pytest.raises(ValidationError):
                await p.execute(action(x=80.5))
            peer.visual["clientWidth"] = 40
            with pytest.raises(ValidationError):
                await p.execute(action(x=40))
            peer.visual["scale"] = 2
            r = await p.execute(action())
            assert r.error.code == "browser.geometry"
            await p.close()
            await s.close()

    asyncio.run(scenario())


def test_utc_clock_rollback_clamped(monkeypatch):
    class Clock:
        calls = 0

        @classmethod
        def now(cls, tz):
            cls.calls += 1
            return datetime(2026, 1, 2, tzinfo=UTC) - timedelta(seconds=cls.calls)

    monkeypatch.setattr("bca.core.browser.input.datetime", Clock)

    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer)
            r = await p.execute(action(A.TEXT_INPUT, text=""))
            assert r.started_at == r.finished_at
            await p.close()
            await s.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kind,kwargs,reject",
    [
        (A.MOUSE_DOWN, {}, "mousePressed"),
        (A.KEY_DOWN, {"key": "a"}, "keyDown"),
        (A.TEXT_INPUT, {"text": "secret"}, "text"),
    ],
)
def test_explicit_rejection_no_release_of_unpressed_key(kind, kwargs, reject, caplog):
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer)
            peer.reject_type = reject
            r = await p.execute(action(kind, **kwargs))
            assert r.status is ActionStatus.FAILED and r.error.code == "browser.command"
            assert r.error.details["outcome_uncertain"] is False
            assert len(peer.inputs) == 1 and p.available
            assert "secret" not in to_json(r) and "private data" not in to_json(r)
            await p.close()
            await s.close()

    asyncio.run(scenario())
    assert "secret" not in caplog.text and "private data" not in caplog.text


def test_stale_waiter_cannot_release_new_bindings_held_input():
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer)
            await p._lock.acquire()
            task = asyncio.create_task(p.execute(action()))
            await asyncio.sleep(0)
            await s.bind("page-b")
            # Establish the state of a later binding before the stale waiter wakes.
            # This explicitly exercises the guard without relying on lock scheduling.
            p._owner = p._identity()
            p._buttons.add(B.RIGHT)
            p._lock.release()
            with pytest.raises(TargetLostError):
                await task
            assert not peer.inputs
            assert p._buttons == {B.RIGHT} and not p.input_state_uncertain
            await p.close()
            assert peer.inputs[-1]["sessionId"] == s.session_id
            await s.close()

    asyncio.run(scenario())


def test_switch_with_old_hold_requires_recovery():
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer)
            await p.execute(action(A.KEY_DOWN, key="Shift"))
            await s.bind("page-b")
            with pytest.raises(TargetLostError):
                await p.execute(action(A.TEXT_INPUT, text="", page_id="page-b"))
            assert p.input_state_uncertain and not p.available
            assert len(peer.inputs) == 1
            await p.close()
            assert len(peer.inputs) == 1
            await s.close()

    asyncio.run(scenario())


def test_target_destroyed_between_click_steps():
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer)

            async def destroy(request):
                if request["params"].get("type") == "mousePressed":
                    await peer.emit("Target.targetDestroyed", {"targetId": "page-a"})

            peer.before_response = destroy
            with pytest.raises(TargetLostError):
                await p.execute(action())
            assert len(peer.inputs) == 1
            assert p.input_state_uncertain
            await p.close()
            await s.close()

    asyncio.run(scenario())


def test_geometry_cancellation_emits_no_input():
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer)
            original = s.send
            gate = asyncio.Event()

            async def send(method, *args, **kwargs):
                if method == "Page.getLayoutMetrics":
                    gate.set()
                    await asyncio.Event().wait()
                return await original(method, *args, **kwargs)

            s.send = send
            task = asyncio.create_task(p.execute(action()))
            await gate.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not peer.inputs and p.available
            await p.close()
            await s.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kind,kwargs,hold",
    [(A.KEY_DOWN, {"key": "Shift"}, "rawKeyDown"), (A.TEXT_INPUT, {"text": "secret"}, "text")],
)
def test_lost_keyboard_or_text_response_never_replayed(kind, kwargs, hold):
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer, timeout=0.03)
            peer.hold_type = hold
            peer.input_gate.clear()
            r = await p.execute(action(kind, **kwargs))
            assert r.error.code == "browser.timeout"
            assert r.error.details["outcome_uncertain"] is True
            assert p.input_state_uncertain
            assert sum(r["params"].get("type", "text") == hold for r in peer.inputs) == 1
            with pytest.raises(CapabilityUnavailableError):
                await p.execute(action(A.TEXT_INPUT, text=""))
            peer.input_gate.set()
            await p.close()
            await s.close()

    asyncio.run(scenario())


def test_cleanup_timeout_is_bounded_and_close_cancellation_is_shielded():
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer)
            await p.execute(action(A.MOUSE_DOWN))
            peer.hold_type = "mouseReleased"
            peer.input_gate.clear()
            closing = asyncio.create_task(p.close())
            await peer.seen("Input.dispatchMouseEvent", 2)
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            async with asyncio.timeout(2):
                await p.close()
            assert p.last_error.code == "browser.input_cleanup"
            assert p.input_state_uncertain and s.is_ready
            assert s.connection.pending_count == 0
            peer.input_gate.set()
            await s.close()

    asyncio.run(scenario())


def test_unexpected_exception_propagates_after_release(monkeypatch):
    async def scenario():
        async with InputPeer() as peer:
            s, p = await ready(peer)
            await p.execute(action(A.KEY_DOWN, key="Shift"))

            async def broken(*args):
                raise RuntimeError("programming bug")

            monkeypatch.setattr("bca.core.browser.input.measure_geometry", broken)
            with pytest.raises(RuntimeError):
                await p.execute(action())
            assert peer.inputs[-1]["params"]["type"] == "keyUp"
            assert p.available
            await p.close()
            await s.close()

    asyncio.run(scenario())
