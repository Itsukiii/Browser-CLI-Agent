import asyncio
import base64
import json
from io import BytesIO

import pytest
from PIL import Image

from bca.core.browser import (
    BrowserCaptureProvider,
    BrowserInputProvider,
    BrowserSession,
    CaptureError,
    CDPTimeoutError,
    EndpointError,
    TargetLostError,
)
from bca.core.errors import CapabilityUnavailableError, ValidationError
from bca.core.protocol import ActionStatus
from bca.core.providers import CaptureProvider, InputProvider, ProviderRegistry
from examples.browser_end_to_end import click_observation, observe, red_center, run_end_to_end

from .test_input import InputPeer, action


async def setup(peer):
    session = BrowserSession(peer.endpoint)
    capture, inputs = BrowserCaptureProvider(session), BrowserInputProvider(session)
    registry = ProviderRegistry()
    registry.register(capture)
    registry.register(inputs)
    assert not registry.available(CaptureProvider) and not registry.available(InputProvider)
    await session.connect()
    await session.bind("page-a")
    await capture.start()
    await inputs.start()
    await capture.start()
    await inputs.start()
    image = BytesIO()
    with Image.new("RGB", (200, 100), (255, 0, 0)) as rgb:
        rgb.save(image, format="PNG")
    peer.screenshot = {"data": base64.b64encode(image.getvalue()).decode()}
    return session, capture, inputs, registry


async def finish(session, capture, inputs):
    await inputs.close()
    await capture.close()
    await inputs.close()
    await capture.close()
    await session.close()
    assert session.connection.pending_count == 0
    assert not session.connection.reader_running and not session.connected


def test_shared_session_registry_pixel_action_and_borrowed_ownership():
    async def scenario():
        async with InputPeer() as peer:
            s, c, i, r = await setup(peer)
            for _ in range(2):
                observation = await observe(s, r, False)
                assert red_center(observation.frame) == (99.5, 49.5)
                result, point = await click_observation(s, r, observation)
                assert result.status is ActionStatus.SUCCEEDED
                assert point == (49.75, 24.75)
                assert peer.inputs[-1]["params"]["x"] == point[0]
            await i.close()
            await c.close()
            assert s.is_ready
            assert await s.send("Test.echo", {"alive": True}) == {"echo": {"alive": True}}
            with pytest.raises(CapabilityUnavailableError):
                r.get(InputProvider)
            await finish(s, c, i)

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["rebind", "switch", "resize", "navigate", "scroll"])
def test_observation_context_rejects_stale_frame_before_any_input(change):
    async def scenario():
        async with InputPeer() as peer:
            s, c, i, r = await setup(peer)
            observed = await observe(s, r, False)
            if change == "rebind":
                await s.unbind()
                await s.bind("page-a")
            elif change == "switch":
                await s.bind("page-b")
            elif change == "resize":
                peer.visual["clientWidth"] = 90
            elif change == "navigate":
                peer.runtime["timeOrigin"] += 1
            else:
                peer.visual["pageX"] += 1
                peer.runtime["x"] += 1
            with pytest.raises((TargetLostError, ValidationError)):
                await click_observation(s, r, observed)
            assert not peer.inputs
            await finish(s, c, i)

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["switch", "rebind", "unbind", "destroy", "disconnect", "close"])
def test_capture_input_and_both_waiters_reject_obsolete_binding(change):
    async def scenario():
        async with InputPeer() as peer:
            s, c, i, r = await setup(peer)
            sid = s.session_id
            peer.gate.clear()
            peer.hold_type = "mousePressed"
            peer.input_gate.clear()
            tasks = [
                asyncio.create_task(c.capture("page-a")),
                asyncio.create_task(i.execute(action())),
            ]
            await peer.seen("Page.captureScreenshot")
            await peer.seen("Input.dispatchMouseEvent")
            tasks += [
                asyncio.create_task(c.capture("page-a")),
                asyncio.create_task(i.execute(action())),
            ]
            await asyncio.sleep(0)
            if change == "switch":
                await s.bind("page-b")
            elif change == "rebind":
                await s.unbind()
                await s.bind("page-a")
            elif change == "unbind":
                await s.unbind()
            elif change == "destroy":
                await peer.emit("Target.targetDestroyed", {"targetId": "page-a"})
            elif change == "disconnect":
                for socket in tuple(peer.connections):
                    await socket.close()
            else:
                await s.close()
            peer.gate.set()
            peer.input_gate.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            assert all(
                isinstance(e, (TargetLostError, CapabilityUnavailableError)) for e in results
            )
            assert all(request["sessionId"] == sid for request in peer.inputs)
            assert s.connection.pending_count == 0
            await finish(s, c, i)

    asyncio.run(scenario())


def test_capture_and_input_independent_timeouts_and_cancel_cleanup():
    async def scenario():
        async with InputPeer() as peer:
            s, c, i, r = await setup(peer)
            c._timeout = 0.03
            peer.gate.clear()
            # Input remains usable while capture waits: there is no new global lock.
            capture = asyncio.create_task(c.capture("page-a"))
            await peer.seen("Page.captureScreenshot")
            assert (await i.execute(action())).status is ActionStatus.SUCCEEDED
            with pytest.raises(CDPTimeoutError):
                await capture
            c._timeout = 10
            peer.gate.set()
            await c.capture("page-a")
            peer.hold_type = "mousePressed"
            peer.input_gate.clear()
            pending = asyncio.create_task(i.execute(action()))
            await peer.seen("Input.dispatchMouseEvent", 3)
            await c.capture("page-a")
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert i.input_state_uncertain
            assert peer.inputs[-1]["params"]["type"] == "mouseReleased"
            peer.input_gate.set()
            await finish(s, c, i)

    asyncio.run(scenario())


def test_capture_and_input_failures_do_not_invalidate_other_capability():
    async def scenario():
        async with InputPeer() as peer:
            s, c, i, r = await setup(peer)
            valid = peer.screenshot
            peer.screenshot = {"data": "invalid"}
            with pytest.raises(CaptureError):
                await c.capture("page-a")
            assert (await i.execute(action())).error is None
            peer.screenshot = valid
            peer.reject_type = "mousePressed"
            assert (await i.execute(action())).status is ActionStatus.FAILED
            assert (await c.capture("page-a")).page_id == "page-a"
            peer.reject_type = None
            peer.after_capture = lambda: peer.runtime.update(timeOrigin=2000)
            with pytest.raises(CaptureError):
                await c.capture("page-a")
            await finish(s, c, i)

    asyncio.run(scenario())


class LifecyclePeer(InputPeer):
    async def _reply(self, socket, request):
        method = request["method"]
        result = None
        if method == "Target.createTarget":
            self.targets["owned"] = {
                "targetId": "owned",
                "type": "page",
                "title": "fixture",
                "url": "about:blank",
            }
            result = {"targetId": "owned"}
        elif method == "Target.closeTarget":
            self.targets.pop(request["params"]["targetId"])
            result = {"success": True}
        elif method == "Target.getTargetInfo":
            result = {"targetInfo": self.targets[request["params"]["targetId"]]}
        if result is not None:
            await socket.send(json.dumps({"id": request["id"], "result": result}))
            return
        await super()._reply(socket, request)


@pytest.mark.parametrize("failure", ["cancel", "startup", "provider_start"])
def test_example_partial_start_or_cancel_closes_only_owned_target(failure, tmp_path, monkeypatch):
    async def scenario():
        async with LifecyclePeer() as peer:
            entered = asyncio.Event()

            async def evaluate(*args):
                entered.set()
                if failure == "provider_start":
                    return True
                if failure == "startup":
                    raise RuntimeError("fixture startup failed")
                await asyncio.Event().wait()

            monkeypatch.setattr("examples.browser_end_to_end.evaluate", evaluate)
            if failure == "provider_start":

                async def start(self):
                    raise RuntimeError("input startup failed after capture started")

                monkeypatch.setattr(BrowserInputProvider, "start", start)
            task = asyncio.create_task(run_end_to_end(peer.endpoint, tmp_path))
            await entered.wait()
            if failure == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                with pytest.raises(RuntimeError):
                    await task
            report = json.loads(
                (tmp_path / "browser-integration-report.json").read_text(encoding="utf8")
            )
            assert report["status"] == "failed"
            assert report["preexisting_targets_preserved"]
            assert report["owned_targets_remaining"] == []
            assert (
                report["cleanup"]["pending_count"] == 0 and not report["cleanup"]["reader_running"]
            )
            assert [
                q["params"]["targetId"]
                for q in peer.requests
                if q["method"] == "Target.closeTarget"
            ] == ["owned"]

    asyncio.run(scenario())


def test_example_repeated_cancel_waits_for_ordered_cleanup(tmp_path, monkeypatch):
    async def scenario():
        async with LifecyclePeer() as peer:
            entered, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

            async def evaluate(*args):
                entered.set()
                await asyncio.Event().wait()

            original = BrowserCaptureProvider.close

            async def close(self):
                closing.set()
                await release.wait()
                await original(self)

            monkeypatch.setattr("examples.browser_end_to_end.evaluate", evaluate)
            monkeypatch.setattr(BrowserCaptureProvider, "close", close)
            task = asyncio.create_task(run_end_to_end(peer.endpoint, tmp_path))
            await entered.wait()
            task.cancel()
            await closing.wait()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            report = json.loads(
                (tmp_path / "browser-integration-report.json").read_text(encoding="utf8")
            )
            assert report["cleanup"]["errors"] == []
            assert report["owned_targets_remaining"] == []
            assert not report["cleanup"]["reader_running"]

    asyncio.run(scenario())


def test_unreachable_endpoint_reports_partial_cleanup(tmp_path):
    async def scenario():
        # A deterministic loopback HTTP failure, without guessing an unused port.
        async with LifecyclePeer() as peer:
            from http import HTTPStatus

            peer.http_status = HTTPStatus.SERVICE_UNAVAILABLE
            with pytest.raises(EndpointError):
                await run_end_to_end(peer.endpoint, tmp_path)
            report = json.loads(
                (tmp_path / "browser-integration-report.json").read_text(encoding="utf8")
            )
            assert report["stage"] == "connect" and report["status"] == "failed"
            assert report["cleanup"]["errors"] == []
            assert not report["cleanup"]["connected"]

    asyncio.run(scenario())
