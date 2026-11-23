"""Actual Maa native jobs with synthetic pixels; deliberately not browser evidence."""

import asyncio
import threading

import pytest

pytest.importorskip("maa")

from bca.lite.bridge import CDPBridge, run_native
from bca.lite.maa_controller import MaaCDPController
from tests.lite.test_cdp_bridge import FakeCapture, FakeInput, FakeSession


@pytest.mark.parametrize("raw", [True, False])
def test_native_callback_color_scaling_and_click(monkeypatch, raw):
    async def scenario():
        owner = threading.get_ident()
        threads = []

        class Controller(MaaCDPController):
            def screencap(self):
                threads.append(threading.get_ident())
                return super().screencap()

            def click(self, x, y):
                threads.append(threading.get_ident())
                return super().click(x, y)

        monkeypatch.setattr(
            "bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g")
        )
        inputs = FakeInput()
        bridge = CDPBridge(
            loop=asyncio.get_running_loop(),
            session=FakeSession(),
            capture=FakeCapture(),
            input_provider=inputs,
        )

        def work():
            ctrl = Controller(bridge, raw_size=raw)
            try:
                assert ctrl.post_connection().wait().succeeded
                if not raw:
                    assert ctrl.set_screenshot_target_short_side(100)
                job = ctrl.post_screencap().wait()
                assert job.succeeded
                bgr = job.get()
                assert bgr.shape == ((40, 80, 3) if raw else (100, 200, 3))
                assert bgr[0, 0].tolist() == [10, 20, 200]
                assert bgr.flags.c_contiguous
                assert ctrl.post_click(20 if raw else 50, 10 if raw else 25).wait().succeeded
                assert not ctrl.post_click(1, 1).wait().succeeded
                assert not ctrl.post_input_text("not supported").wait().succeeded
            finally:
                ctrl.close()
                ctrl.close()

        await run_native(bridge, work)
        await bridge.aclose()
        assert inputs.actions[0].x == 20 and inputs.actions[0].y == 10
        assert len(inputs.actions) == 1
        assert threads and all(t != owner for t in threads)

    asyncio.run(scenario())


def test_resource_tasker_real_binding(tmp_path, monkeypatch):
    import json

    from maa.library import Library
    from maa.pipeline import JDirectHit, JDoNothing
    from maa.resource import Resource
    from maa.tasker import Tasker

    async def scenario():
        monkeypatch.setattr(
            "bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g")
        )
        bridge = CDPBridge(
            loop=asyncio.get_running_loop(),
            session=FakeSession(),
            capture=FakeCapture(),
            input_provider=FakeInput(),
        )
        bundle = tmp_path / "bundle"
        (bundle / "pipeline").mkdir(parents=True)
        (bundle / "pipeline" / "test.json").write_text(
            json.dumps({"Probe": {"recognition": "DirectHit", "action": "DoNothing"}}),
            encoding="utf-8",
        )

        def work():
            ctrl = MaaCDPController(bridge)
            resource = Resource()
            tasker = Tasker()
            try:
                assert ctrl.post_connection().wait().succeeded
                assert resource.post_bundle(bundle).wait().succeeded
                assert tasker.bind(resource, ctrl) and tasker.inited
                assert tasker.post_task("Probe").wait().succeeded
                image = ctrl.post_screencap().wait().get()
                assert tasker.post_recognition("DirectHit", JDirectHit(), image).wait().succeeded
                assert tasker.post_action("DoNothing", JDoNothing()).wait().succeeded
                with pytest.raises(TypeError):
                    tasker.post_recognition("DirectHit", {}, image)
            finally:
                tasker.post_stop().wait()
                Library.framework().MaaTaskerDestroy(tasker._handle)
                tasker._handle = None
                ctrl.close()
                Library.framework().MaaResourceDestroy(resource._handle)
                resource._handle = None

        await run_native(bridge, work)
        await bridge.aclose()

    asyncio.run(scenario())


def test_native_cancel_during_callback_drains_before_return(monkeypatch):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        finished = threading.Event()

        class Capture(FakeCapture):
            async def capture(self, page):
                entered.set()
                await release.wait()
                return await super().capture(page)

        monkeypatch.setattr(
            "bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g")
        )
        inputs = FakeInput()
        bridge = CDPBridge(
            loop=asyncio.get_running_loop(),
            session=FakeSession(),
            capture=Capture(),
            input_provider=inputs,
        )

        def work():
            ctrl = MaaCDPController(bridge)
            try:
                assert ctrl.post_connection().wait().succeeded
                assert not ctrl.post_screencap().wait().succeeded
                assert not ctrl.post_click(1, 1).wait().succeeded
            finally:
                ctrl.close()
                finished.set()

        task = asyncio.create_task(run_native(bridge, work))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await bridge.aclose()
        assert finished.is_set() and not inputs.actions

    asyncio.run(scenario())


def test_native_input_missing_ack_blocks_real_browser_provider():
    # Simulated CDP transport + production Session/Capture/Input + real Maa DLL.
    # This is fault injection, not an Edge test.
    from bca.core.browser import BrowserCaptureProvider
    from tests.core.browser.test_input import InputPeer, ready

    async def scenario():
        async with InputPeer() as peer:
            session, inputs = await ready(peer, timeout=0.05)
            capture = BrowserCaptureProvider(session)
            await capture.start()
            bridge = CDPBridge(
                loop=asyncio.get_running_loop(),
                session=session,
                capture=capture,
                input_provider=inputs,
                timeout=2,
            )
            peer.hold_type = "mousePressed"
            peer.input_gate.clear()

            def work():
                ctrl = MaaCDPController(bridge)
                try:
                    assert ctrl.post_connection().wait().succeeded
                    assert ctrl.post_screencap().wait().succeeded
                    assert not ctrl.post_click(10, 10).wait().succeeded
                    assert bridge.input_outcome == "unknown"
                    assert not ctrl.post_screencap().wait().succeeded
                    assert not ctrl.post_click(10, 10).wait().succeeded
                finally:
                    ctrl.close()

            try:
                await run_native(bridge, work)
                assert inputs.input_state_uncertain
                assert len([r for r in peer.inputs if r["params"]["type"] == "mousePressed"]) == 1
                assert inputs.last_error.details["input_attempted"]
            finally:
                peer.input_gate.set()
                await bridge.aclose()
                await inputs.close()
                await capture.close()
                await session.close()
            assert session.connection.pending_count == 0
            assert not session.connection.reader_running

    asyncio.run(scenario())
