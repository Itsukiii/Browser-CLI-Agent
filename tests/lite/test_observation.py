"""Real Maa + controlled Provider; no Edge or three-minute 02.3 claim."""
# ruff: noqa: E402

import asyncio
import dataclasses
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("maa")
from bca.lite.observation import ObservationCoordinator
from bca.lite.plugin import ActionIntent, BusinessState, VisualTarget
from bca.lite.vision import MaaVisionFacade
from bca.lite.vision_resources import ResourceSpec
from bca.lite.vision_types import RecognitionStatus, VisionError
from examples.plugins.lite_fixture import FixturePlugin
from tests.lite.test_vision_native import model_spec, record
from tests.lite.vision_fixture import bridge_for, bundle_at, scene


def setup(tmp_path, monkeypatch, *, model=None, interval=100, capacity=16):
    bridge, capture, session, inputs = bridge_for(monkeypatch, scene(text="123"), max_frame_age=5)
    spec = ResourceSpec(bundle_at(tmp_path / "bundle"), model)
    facade = MaaVisionFacade(bridge, spec)
    plugin = FixturePlugin(spec)
    coordinator = ObservationCoordinator(
        facade, plugin, interval=interval, notification_capacity=capacity
    )
    return coordinator, facade, plugin, bridge, capture, session, inputs


def test_content_dedup_real_refresh_status_recovery(tmp_path, monkeypatch):
    async def run():
        c, f, p, b, capture, _, _ = setup(tmp_path, monkeypatch, capacity=2)
        await c.start()
        try:
            one = await c.refresh()
            two = await c.refresh()
            assert one.source is not two.source and one.state == two.state
            assert c.take_change().sequence == 1 and c.take_change() is None
            read = await c.execute_text("?")
            assert capture.count == 3 and read.observation.source is not two.source
            states = []
            for image in [scene(points=()), scene(points=((60, 50), (150, 50))), scene()]:
                capture.image = image
                states.append((await c.refresh()).state.status)
            original = p.observe
            monkeypatch.setattr(
                p, "observe", lambda _: (_ for _ in ()).throw(ValueError("bad parse"))
            )
            states.append((await c.refresh()).state.status)
            monkeypatch.setattr(p, "observe", original)
            states.append((await c.refresh()).state.status)
            assert states == [
                RecognitionStatus.NOT_FOUND,
                RecognitionStatus.AMBIGUOUS,
                RecognitionStatus.MATCHED,
                RecognitionStatus.ERROR,
                RecognitionStatus.MATCHED,
            ]
            assert c.stats.dropped_notifications == 3
            assert one.state.status == RecognitionStatus.MATCHED  # Published state unchanged.
            record(
                tmp_path,
                "dedup",
                {
                    "states": states,
                    "stats": dataclasses.asdict(c.stats),
                    "frames": [one.source.frame.frame_id, two.source.frame.frame_id],
                },
            )
        finally:
            assert (await c.aclose()).released

    asyncio.run(run())


def test_periodic_effective_frequency_heartbeat_stop_restart(tmp_path, monkeypatch):
    async def run():
        c, f, p, b, capture, _, _ = setup(tmp_path, monkeypatch, interval=0.5)
        times, beats = [], []
        original = p.observe

        def observed(batch):
            times.append(time.monotonic())
            return original(batch)

        monkeypatch.setattr(p, "observe", observed)

        async def heartbeat():
            for _ in range(110):
                beats.append(time.monotonic())
                await asyncio.sleep(0.05)

        await c.start()
        await asyncio.gather(heartbeat(), asyncio.sleep(5.5))
        await asyncio.gather(c.stop(), c.stop())
        count = capture.count
        await asyncio.sleep(0.1)
        assert capture.count == count
        rate = (len(times) - 1) / (times[-1] - times[0])
        assert rate >= 1 and c.stats.valid >= 8 and len(beats) == 110
        assert max(b - a for a, b in zip(beats, beats[1:], strict=False)) < 0.5
        await c.start()
        await c.refresh()
        assert capture.count > count
        report = await c.aclose()
        assert report.released and await c.aclose() is report
        with pytest.raises(VisionError):
            await c.start()
        record(
            tmp_path,
            "frequency",
            {
                "completed_at": times,
                "heartbeat": beats,
                "effective_hz": rate,
                "stats": dataclasses.asdict(c.stats),
            },
        )

    asyncio.run(run())


def test_command_serialization_exact_authorization_and_post_observation(tmp_path, monkeypatch):
    model = model_spec()

    async def run():
        c, f, p, b, capture, _, inputs = setup(tmp_path, monkeypatch, model=model)
        await c.start()
        entered, release = asyncio.Event(), asyncio.Event()
        original = inputs.execute

        async def held(action):
            entered.set()
            await release.wait()
            capture.image = scene(text="124")
            return await original(action)

        monkeypatch.setattr(inputs, "execute", held)
        refs = []
        authorize = b.authorize

        async def authorized(ref):
            assert ref is b.observation
            refs.append(ref)
            await authorize(ref)

        monkeypatch.setattr(b, "authorize", authorized)
        try:
            command = asyncio.create_task(c.execute_text("click 123"))
            await asyncio.wait_for(entered.wait(), 5)
            waiting = asyncio.create_task(c.refresh())
            await asyncio.sleep(0.05)
            assert capture.count == 1 and not waiting.done()
            release.set()
            result, refreshed = await asyncio.gather(command, waiting)
            assert result.outcome == "confirmed" and len(inputs.actions) == 1
            assert result.observation.state.interaction_revision == "124"
            assert refreshed.source is not result.observation.source
            assert len(refs) == 1 and refs[0] is not result.observation.source
            assert (inputs.actions[0].x, inputs.actions[0].y) == (77, 63)
            record(
                tmp_path,
                "command",
                {
                    "outcome": result.outcome,
                    "post_revision": "124",
                    "capture_count": capture.count,
                    "authorized_frame": refs[0].frame.frame_id,
                    "input": [inputs.actions[0].x, inputs.actions[0].y],
                },
            )
        finally:
            release.set()
            assert (await c.aclose()).released

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["revision", "missing_revision", "deadline", "target", "ambiguous"]
)
def test_write_rejections_no_input(tmp_path, monkeypatch, fault):
    model = model_spec()

    async def run():
        c, f, p, b, capture, _, inputs = setup(tmp_path, monkeypatch, model=model)
        await c.start()
        if fault == "ambiguous":
            capture.image = scene(points=((60, 50), (150, 50)))
        if fault in ("missing_revision", "target"):
            original = p.observe

            def changed(batch):
                state = original(batch)
                return (
                    dataclasses.replace(state, interaction_revision=None)
                    if fault == "missing_revision"
                    else dataclasses.replace(state, targets=(VisualTarget("button", "invented"),))
                )

            monkeypatch.setattr(p, "observe", changed)
        try:
            intent = ActionIntent(
                "click",
                "button",
                "wrong" if fault == "revision" else "123",
                time.monotonic() + (-1 if fault == "deadline" else 10),
            )
            with pytest.raises(VisionError):
                await c.execute_intent(intent)
            assert not inputs.actions
            record(tmp_path, f"reject-{fault}", {"inputs": 0, "captures": capture.count})
        finally:
            assert (await c.aclose()).released

    asyncio.run(run())


def test_unknown_input_retires_no_replay(tmp_path, monkeypatch):
    model = model_spec()

    async def run():
        c, f, p, b, capture, _, inputs = setup(tmp_path, monkeypatch, model=model)
        await c.start()

        async def fail(action):
            inputs.actions.append(action)
            raise RuntimeError("ack lost")

        monkeypatch.setattr(inputs, "execute", fail)
        try:
            result = await c.execute_text("click 123")
            assert result.outcome == "unknown" and result.observation.source is None
            with pytest.raises(VisionError):
                await c.execute_text("click 123")
            assert len(inputs.actions) == 1
            record(tmp_path, "unknown", {"outcome": result.outcome, "inputs": 1})
        finally:
            assert (await c.aclose()).released

    asyncio.run(run())


def test_cancel_refresh_drains_and_closes(tmp_path, monkeypatch):
    async def run():
        c, f, p, b, capture, _, inputs = setup(tmp_path, monkeypatch)
        await c.start()
        entered, release = asyncio.Event(), asyncio.Event()
        original = capture.capture

        async def held(page):
            entered.set()
            await release.wait()
            return await original(page)

        monkeypatch.setattr(capture, "capture", held)
        task = asyncio.create_task(c.refresh())
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0.02)
        task.cancel()
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert f.close_report.released and not b.connected and not inputs.actions
        assert (await c.aclose()).released
        record(tmp_path, "cancel", dataclasses.asdict(f.close_report))

    asyncio.run(run())


def test_immutable_payload():
    with pytest.raises(ValueError):
        BusinessState(RecognitionStatus.MATCHED, {"mutable": 1}, ())


def test_destroy_uncertain_never_retries_pointer(monkeypatch):
    from maa.library import Library

    from bca.lite._native_vision import _QUARANTINED, NativeVision

    # Fake handles deliberately prevent a real leak/double free during uncertain-outcome injection.
    owner = NativeVision(None, None, True)
    stop = SimpleNamespace(succeeded=True)
    stop.wait = lambda: stop
    owner.tasker = SimpleNamespace(_handle=111, inited=True, running=False, post_stop=lambda: stop)
    owner.controller = SimpleNamespace(_handle=222)
    owner.resource = SimpleNamespace(_handle=333)
    calls = []

    def uncertain(handle):
        calls.append(handle)
        raise RuntimeError("unknown whether release occurred")

    monkeypatch.setattr(Library.framework(), "MaaTaskerDestroy", uncertain)
    try:
        first, second = owner.close(), owner.close()
        assert not first.released and not second.released and calls == [111]
        assert owner._quarantined_handles == (111, 222, 333)
        assert owner.tasker._handle is None  # Disarmed, not claimed released.
    finally:
        _QUARANTINED.remove(owner)
