"""Lifecycle/command races with real native work and controlled input/capture providers."""

# ruff: noqa: E402
import asyncio
import dataclasses
from types import SimpleNamespace

import pytest

pytest.importorskip("maa")
from bca.lite.vision_types import VisionError
from tests.lite.test_observation import setup
from tests.lite.test_vision_native import model_spec, record


@pytest.mark.parametrize("operation", ["stop", "close", "cancel"])
def test_command_inflight_shutdown(tmp_path, monkeypatch, operation):
    model = model_spec()

    async def run():
        c, f, p, b, capture, _, inputs = setup(tmp_path, monkeypatch, model=model)
        await c.start()
        entered, release = asyncio.Event(), asyncio.Event()
        original = inputs.execute

        async def held(action):
            entered.set()
            await release.wait()
            return await original(action)

        monkeypatch.setattr(inputs, "execute", held)
        task = asyncio.create_task(c.execute_text("click 123"))
        await asyncio.wait_for(entered.wait(), 5)
        if operation == "cancel":
            task.cancel()
            closing = None
        else:
            closing = asyncio.create_task(c.stop() if operation == "stop" else c.aclose())
        await asyncio.sleep(0.02)
        assert not task.done() and (closing is None or not closing.done())
        release.set()
        if operation == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await task
            assert f.close_report.released
        else:
            assert (await task).outcome == "confirmed"
            await closing
        assert len(inputs.actions) == 1
        assert (await c.aclose()).released
        record(
            tmp_path,
            f"command-{operation}",
            {"inputs": len(inputs.actions), "close": dataclasses.asdict(f.close_report)},
        )

    asyncio.run(run())


def test_close_failure_propagates_and_can_retry_stop(tmp_path, monkeypatch):
    async def run():
        c, f, p, b, _, _, _ = setup(tmp_path, monkeypatch)
        await c.start()
        stops = SimpleNamespace(succeeded=False)
        stops.wait = lambda: stops
        with monkeypatch.context() as patch:
            patch.setattr(f._native.tasker, "post_stop", lambda: stops)
            failed = await c.aclose()
        assert not failed.released and failed.stop_status == "failed"
        assert b.connected  # No closing borrowed dependencies after failed native stop.
        with pytest.raises(VisionError):
            await c.refresh()
        recovered = await c.aclose()
        assert recovered.released and not b.connected
        record(
            tmp_path,
            "coordinator-stop-failure",
            {"failed": dataclasses.asdict(failed), "recovered": dataclasses.asdict(recovered)},
        )

    asyncio.run(run())


def test_snapshot_copy_and_old_batch_cannot_authorize(tmp_path, monkeypatch):
    from bca.lite.vision_types import TemplateRequest

    async def run():
        c, f, p, b, _, _, inputs = setup(tmp_path, monkeypatch)
        await f.start()
        batch = await f.recognize((TemplateRequest("button", "marker.png"),))
        with pytest.raises(VisionError):
            await f.click(dataclasses.replace(batch), "button", 0)
        await f.recognize((TemplateRequest("button", "marker.png"),))
        with pytest.raises(VisionError):
            await f.click(batch, "button", 0)
        assert not inputs.actions and (await c.aclose()).released

    asyncio.run(run())


def test_stop_start_overlap_no_duplicate_periodic_task(tmp_path, monkeypatch):
    async def run():
        c, f, p, b, capture, _, _ = setup(tmp_path, monkeypatch, interval=0.05)
        await c.start()
        for _ in range(5):
            await asyncio.gather(c.stop(), c.start())
        await asyncio.sleep(0.22)
        await c.stop()
        assert capture.count <= 5
        assert (await c.aclose()).released

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["failed", "still_running", "exception"])
def test_stop_failure_never_calls_destroy(monkeypatch, failure):
    from maa.library import Library

    from bca.lite._native_vision import NativeVision

    owner = NativeVision(None, None, True)
    stop = SimpleNamespace(succeeded=failure != "failed")

    def wait():
        if failure == "exception":
            raise RuntimeError("stop wait failed")
        return stop

    stop.wait = wait
    owner.tasker = SimpleNamespace(
        _handle=11, inited=True, running=failure == "still_running", post_stop=lambda: stop
    )
    owner.controller = SimpleNamespace(_handle=22)
    owner.resource = SimpleNamespace(_handle=33)
    calls = []
    monkeypatch.setattr(Library.framework(), "MaaTaskerDestroy", lambda h: calls.append(h))
    report = owner.close()
    assert not report.released and report.errors and not calls
    assert (
        owner.tasker._handle == 11
        and owner.controller._handle == 22
        and owner.resource._handle == 33
    )


def test_successful_stop_waits_for_idle_before_destroy(monkeypatch):
    from maa.library import Library

    from bca.lite._native_vision import NativeVision

    owner = NativeVision(None, None, True)
    reads = []

    class SettlingTasker:
        _handle = 11
        inited = True

        @property
        def running(self):
            reads.append(len(reads))
            return len(reads) <= 3

        def post_stop(self):
            return SimpleNamespace(wait=lambda: SimpleNamespace(succeeded=True))

    owner.tasker = SettlingTasker()
    calls = []

    def destroy(handle):
        assert not owner.tasker.running
        calls.append(handle)

    monkeypatch.setattr(Library.framework(), "MaaTaskerDestroy", destroy)
    report = owner.close()
    assert report.released and calls == [11] and len(reads) >= 4


def test_plugin_close_error_report_and_retry(tmp_path, monkeypatch):
    async def run():
        c, f, p, b, _, _, _ = setup(tmp_path, monkeypatch)
        await c.start()
        with monkeypatch.context() as patch:
            patch.setattr(p, "close", lambda: (_ for _ in ()).throw(ValueError("close error")))
            report = await c.aclose()
        assert report.released and report.errors
        assert not (await c.aclose()).errors

    asyncio.run(run())


def test_stop_during_start_leaves_coordinator_paused(tmp_path, monkeypatch):
    async def run():
        c, f, p, b, capture, _, _ = setup(tmp_path, monkeypatch, interval=0.02)
        entered, release = asyncio.Event(), asyncio.Event()
        original = f.start

        async def held():
            await original()
            entered.set()
            await release.wait()

        monkeypatch.setattr(f, "start", held)
        starting = asyncio.create_task(c.start())
        await entered.wait()
        stopping = asyncio.create_task(c.stop())
        await asyncio.sleep(0.01)
        release.set()
        await asyncio.gather(starting, stopping)
        await asyncio.sleep(0.05)
        assert capture.count == 0
        with pytest.raises(VisionError):
            await c.refresh()
        assert (await c.aclose()).released

    asyncio.run(run())
