"""02.3 real CDP -> Maa -> pure plugin -> coordinator -> visual click / DOM oracle."""

# ruff: noqa: E402
import asyncio
import dataclasses
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

import pytest

pytest.importorskip("maa")
from PIL import Image

from bca.core.browser import BrowserCaptureProvider, BrowserInputProvider, BrowserSession
from bca.lite.bridge import BridgeError, CDPBridge
from bca.lite.fixture import FixturePlugin, fixture_bundle, fixture_html
from bca.lite.observation import ObservationCoordinator
from bca.lite.vision import MaaVisionFacade
from bca.lite.vision_resources import ResourceSpec
from bca.lite.vision_types import RecognitionStatus, VisionError
from examples.browser_end_to_end import evaluate
from tests.lite.test_real_addendum import desktop_key, finish, metrics
from tests.lite.test_vision_native import model_spec, result_record

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(
        not os.environ.get("BCA_CDP_ENDPOINT"), reason="explicit isolated Edge required"
    ),
]


class MeasuredFacade(MaaVisionFacade):
    """Test-only phase instrumentation; no scheduler or native behavior changes."""

    async def _submit(self, operation):
        started = time.monotonic()
        try:
            return await super()._submit(operation)
        finally:
            if getattr(operation, "__name__", "") == "capture":
                self.capture_seconds = time.monotonic() - started
            else:
                self.native_seconds = time.monotonic() - started

    async def recognize(self, requests):
        batch = await super().recognize(requests)
        self.last_batch = batch
        return batch


class MeasuredPlugin(FixturePlugin):
    def observe(self, results):
        started = time.monotonic()
        state = super().observe(results)
        self.parse_seconds = time.monotonic() - started
        return state


class MeasuredCoordinator(ObservationCoordinator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    async def _refresh_locked(self):
        started = time.monotonic()
        observation, batch = await super()._refresh_locked()
        self.records.append(
            {
                "started": started,
                "completed": observation.completed_at,
                "total": time.monotonic() - started,
                "capture": getattr(self._facade, "capture_seconds", None),
                "native": getattr(self._facade, "native_seconds", None),
                "parse": getattr(self._plugin, "parse_seconds", None),
                "sequence": observation.sequence,
                "status": observation.state.status.value,
                "revision": observation.state.interaction_revision,
                "expired": observation.expired,
                "batch": result_record(batch) if batch else None,
            }
        )
        if os.environ.get("BCA_REAL_VISION_EVIDENCE"):
            path = Path(os.environ["BCA_REAL_VISION_EVIDENCE"]) / "observations.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(self.records[-1]) + "\n")
        return observation, batch


async def settle(session):
    # A hidden/minimized desktop can suspend requestAnimationFrame indefinitely.
    # Stimulus JS is synchronous; flush layout and let CDP screenshot capture paint.
    await session.send("Page.bringToFront")
    await evaluate(session, "document.body.offsetHeight")
    await asyncio.sleep(0.05)


async def create(session, bundle, *, window=False):
    target = (
        await session.connection.send(
            "Target.createTarget",
            {
                "url": "data:text/html;charset=utf-8," + quote(fixture_html(bundle)),
                "newWindow": window,
            },
        )
    )["targetId"]
    await session.bind(target)
    await session.send("Page.bringToFront")
    async with asyncio.timeout(10):
        while not await evaluate(session, "typeof configure==='function'"):
            await asyncio.sleep(0.02)
    return target


async def composition(session, capture, inputs, bundle, temp, *, raw, roi, interval=3600):
    # Only viewport dimensions enter preparation. Templates derive from the owned
    # source asset, never a crop of the observed screenshot / a DOM target box.
    frame = await capture.capture(session.page_id)
    scale = frame.width / frame.viewport.capture_width
    if not raw:
        scale *= 720 / min(frame.width, frame.height)
    shutil.copytree(bundle, temp)
    with Image.open(bundle / "image/marker.png") as image:
        image.resize((round(96 * scale), round(64 * scale)), Image.Resampling.BILINEAR).save(
            temp / "image/marker.png"
        )
    resources = ResourceSpec(temp.resolve(), model_spec())
    bridge = CDPBridge(
        loop=asyncio.get_running_loop(),
        session=session,
        capture=capture,
        input_provider=inputs,
        require_authorization=True,
        max_frame_age=5,
    )
    facade = MeasuredFacade(bridge, resources, raw_size=raw)
    plugin = MeasuredPlugin(resources, roi=roi)
    coordinator = MeasuredCoordinator(facade, plugin, interval=interval)
    await coordinator.start()
    return coordinator, facade, bridge


def output(tmp_path, name):
    root = Path(os.environ.get("BCA_REAL_VISION_EVIDENCE", str(tmp_path))) / name
    root.mkdir(parents=True, exist_ok=False)
    return root


async def run_matrix(tmp_path, out, zoom=False):
    session = BrowserSession(os.environ["BCA_CDP_ENDPOINT"])
    capture, inputs = BrowserCaptureProvider(session), BrowserInputProvider(session)
    report = {"cases": [], "status": "running"}
    coordinator = target = None
    await session.connect()
    original = {t.target_id for t in await session.list_targets()}
    try:
        with fixture_bundle() as bundle:
            target = await create(session, bundle, window=zoom)
            await capture.start()
            await inputs.start()
            conditions = (
                [(0.8, True, True), (1, True, False), (1.25, False, True)]
                if zoom
                else [
                    (dpr, raw, roi)
                    for dpr in (1, 1.5, 2)
                    for raw in (True, False)
                    for roi in (True, False)
                ]
            )
            for index, (factor, raw, roi) in enumerate(conditions):
                if zoom:
                    desktop_key(0x30)
                    await asyncio.sleep(0.3)
                    baseline = await metrics(session)
                    if factor != 1:
                        for _ in range(2):
                            desktop_key(0xBD if factor < 1 else 0xBB)
                    await asyncio.sleep(0.3)
                else:
                    await session.send(
                        "Emulation.setDeviceMetricsOverride",
                        {"width": 640, "height": 400, "deviceScaleFactor": factor, "mobile": False},
                    )
                await evaluate(session, "configure()")
                await settle(session)
                coordinator, facade, bridge = await composition(
                    session, capture, inputs, bundle, tmp_path / f"bundle-{index}", raw=raw, roi=roi
                )
                case = {
                    "factor": factor,
                    "raw": raw,
                    "roi": roi,
                    "metrics": await metrics(session),
                    "records": coordinator.records,
                }
                report["cases"].append(case)
                if zoom:
                    case["baseline"] = baseline
                    actual = case["metrics"]["runtime"]
                    assert abs(actual["dpr"] / baseline["runtime"]["dpr"] - factor) < 0.01
                    assert abs(actual["scale"] - 1) < 0.01
                first = await coordinator.refresh()
                case["initial_status"] = first.state.status.value
                if first.state.status == RecognitionStatus.AMBIGUOUS and not roi:
                    # Full-image OCR sees a competing glyph in this marker at
                    # some scales. It must reject; ROI is an explicit new plan,
                    # not selecting best or editing the recognized text.
                    with pytest.raises(VisionError):
                        await coordinator.execute_text("click 123")
                    assert not await evaluate(session, "hits.length")
                    coordinator._plugin.roi = True
                    case["explicit_roi_recovery"] = True
                    first = await coordinator.refresh()
                batch = facade.last_batch
                (out / f"input-{index}.png").write_bytes(batch.capture.source_ref.frame.data)
                Image.fromarray(batch.capture.image[:, :, ::-1]).save(out / f"maa-{index}.png")
                assert first.state.status == RecognitionStatus.MATCHED, case
                assert first.state.interaction_revision == "123"
                box = batch.results[0].candidates[0].box
                frame = batch.capture.source_ref.frame
                x, y = frame.pixel_to_css(
                    box[0] * frame.width / batch.capture.width,
                    box[1] * frame.height / batch.capture.height,
                )
                oracle = await evaluate(
                    session,
                    "(()=>{let r=document.getElementById('button').getBoundingClientRect();"
                    "return {x:r.x,y:r.y,width:r.width,height:r.height}})()",
                )
                case["position_error_css"] = [x - oracle["x"], y - oracle["y"]]
                assert max(abs(v) for v in case["position_error_css"]) <= 2
                changed = coordinator.take_change()
                assert changed is not None
                while coordinator.take_change() is not None:
                    pass
                fresh = await coordinator.execute_text("?")
                assert fresh.observation.source is not first.source
                assert coordinator.take_change() is None
                with pytest.raises(VisionError):
                    await facade.click(batch, "button", 0)
                assert not await evaluate(session, "hits.length")
                action = await coordinator.execute_text("click 123")
                case["action"] = action.outcome
                case["dom"] = await evaluate(session, "hits")
                assert action.outcome == "confirmed"
                assert case["dom"][-1]["id"] == "button"
                assert action.observation.state.interaction_revision == "124"
                count = len(case["dom"])
                with pytest.raises(VisionError):
                    await coordinator.execute_text("click 123")
                assert await evaluate(session, "hits.length") == count
                # Ten digits, three negatives and three multi-digit numbers are
                # exercised across real rendering/font/position conditions.
                texts = [
                    str(index % 10),
                    ("-1", "-20", "-305")[index % 3],
                    ("12", "345", "6789")[index % 3],
                ]
                for text in texts:
                    font = ("Arial", "Georgia", "Courier New")[index % 3]
                    size = (40, 48, 56)[index % 3]
                    await evaluate(
                        session,
                        f"configure({json.dumps(text)},1,{json.dumps(font)},{size},100)",
                    )
                    await settle(session)
                    obs = await coordinator.refresh()
                    Image.fromarray(facade.last_batch.capture.image[:, :, ::-1]).save(
                        out / f"font-{index}-{text}.png"
                    )
                    case.setdefault("font_samples", []).append(
                        {
                            "expected": text,
                            "font": font,
                            "size": size,
                            "actual": obs.state.interaction_revision,
                            "status": obs.state.status.value,
                        }
                    )
                    if obs.state.status == RecognitionStatus.MATCHED:
                        assert obs.state.interaction_revision == text
                    else:
                        assert obs.state.status in (
                            RecognitionStatus.AMBIGUOUS,
                            RecognitionStatus.NOT_FOUND,
                        )
                        with pytest.raises(VisionError):
                            await coordinator.execute_text(f"click {text}")
                        assert await evaluate(session, "hits.length") == count
                for count, expected in [
                    (0, RecognitionStatus.NOT_FOUND),
                    (2, RecognitionStatus.AMBIGUOUS),
                    (1, RecognitionStatus.MATCHED),
                ]:
                    await evaluate(session, f"configure('123',{count})")
                    await settle(session)
                    obs = await coordinator.refresh()
                    assert obs.state.status == expected
                    if count != 1:
                        with pytest.raises(VisionError):
                            await coordinator.execute_text("click 123")
                case["close"] = dataclasses.asdict(await coordinator.aclose())
                assert case["close"]["released"]
                coordinator = None
                await evaluate(session, "hits=[]")
            if zoom:
                desktop_key(0x30)
            report["status"] = "passed"
    finally:
        if coordinator is not None:
            report["last_close"] = dataclasses.asdict(await coordinator.aclose())
        await finish(session, capture, inputs, target, original, report)
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def test_edge_visual_matrix(tmp_path):
    asyncio.run(run_matrix(tmp_path, output(tmp_path, "matrix")))


def test_edge_visual_desktop_zoom(tmp_path):
    asyncio.run(run_matrix(tmp_path, output(tmp_path, "zoom"), zoom=True))


@pytest.mark.skipif(not os.environ.get("BCA_LONG_RUN"), reason="explicit 3 minute run")
def test_edge_sustained_observation(tmp_path):
    out = output(tmp_path, "sustained")

    async def run():
        assert "cv2" not in sys.modules and "bca.plugin_sdk.vision" not in sys.modules
        session = BrowserSession(os.environ["BCA_CDP_ENDPOINT"])
        capture, inputs = BrowserCaptureProvider(session), BrowserInputProvider(session)
        report = {"status": "running", "changes": [], "stimuli": []}
        coordinator = target = None
        await session.connect()
        original = {t.target_id for t in await session.list_targets()}
        try:
            with fixture_bundle() as bundle:
                target = await create(session, bundle)
                await session.send(
                    "Emulation.setDeviceMetricsOverride",
                    {"width": 640, "height": 400, "deviceScaleFactor": 1, "mobile": False},
                )
                await capture.start()
                await inputs.start()
                coordinator, facade, bridge = await composition(
                    session,
                    capture,
                    inputs,
                    bundle,
                    tmp_path / "bundle",
                    raw=True,
                    roi=True,
                    interval=0.75,
                )
                report["records"] = coordinator.records
                started = time.monotonic()
                report["started_monotonic"] = started
                stage = 0
                heartbeat = 0
                # Periodic coordinator performs the observations. This loop is
                # only the independent stimulus/notification/heartbeat consumer.
                while time.monotonic() - started < 185:
                    elapsed = time.monotonic() - started
                    if stage == 0 and elapsed >= 40:
                        await evaluate(session, "configure('456',1)")
                        stage = 1
                        report["stimuli"].append({"elapsed": elapsed, "revision": "456"})
                    elif stage == 1 and elapsed >= 80:
                        await evaluate(session, "configure('456',0)")
                        stage = 2
                        report["stimuli"].append({"elapsed": elapsed, "count": 0})
                    elif stage == 2 and elapsed >= 85:
                        await evaluate(session, "configure('789',1)")
                        stage = 3
                        report["stimuli"].append({"elapsed": elapsed, "revision": "789"})
                    elif stage == 3 and elapsed >= 120:
                        result = await coordinator.execute_text("click 789")
                        report["action"] = result.outcome
                        assert result.outcome == "confirmed"
                        assert result.observation.state.interaction_revision == "790"
                        stage = 4
                    while (change := coordinator.take_change()) is not None:
                        report["changes"].append(dataclasses.asdict(change))
                    heartbeat += 1
                    await asyncio.sleep(0.05)
                await coordinator.stop()
                duration = time.monotonic() - started
                report["duration"] = duration
                report["heartbeat"] = heartbeat
                report["stats"] = dataclasses.asdict(coordinator.stats)
                report["effective_hz"] = coordinator.stats.valid / duration
                report["dom"] = await evaluate(session, "hits")
                assert duration >= 180 and coordinator.stats.valid >= 120
                assert report["effective_hz"] >= 1
                assert heartbeat >= 2000
                statuses = {r["status"] for r in coordinator.records}
                assert statuses == {"MATCHED", "NOT_FOUND"}
                assert len(report["changes"]) == 5
                assert len(report["dom"]) == 1 and report["dom"][0]["id"] == "button"
                batches = [r["batch"] for r in coordinator.records]
                assert len({b["frame_id"] for b in batches}) == len(batches)
                report["close"] = dataclasses.asdict(await coordinator.aclose())
                assert report["close"]["released"]
                native = facade._native
                report["handles_after"] = {
                    name: bool(getattr(getattr(native, name), "_handle", None))
                    for name in ("tasker", "controller", "resource")
                }
                assert not any(report["handles_after"].values())
                report["native_workers_after"] = [
                    t.name for t in threading.enumerate() if t.name.startswith("bca-maa-vision")
                ]
                assert not report["native_workers_after"]
                report["cv2_loaded"] = "cv2" in sys.modules
                report["legacy_vision_loaded"] = "bca.plugin_sdk.vision" in sys.modules
                assert not report["cv2_loaded"] and not report["legacy_vision_loaded"]
                coordinator = None
                report["status"] = "passed"
        finally:
            if coordinator is not None:
                report["last_close"] = dataclasses.asdict(await coordinator.aclose())
            await finish(session, capture, inputs, target, original, report)
            (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["navigate", "target_closed", "capture_timeout", "cancel"])
def test_edge_visual_retirement(tmp_path, fault):
    out = output(tmp_path, fault)

    class DelayedCapture(BrowserCaptureProvider):
        delay = False

        async def capture(self, page_id):
            if self.delay:
                entered.set()
                await asyncio.sleep(0.3)
            return await super().capture(page_id)

    async def run():
        nonlocal entered
        entered = asyncio.Event()
        session = BrowserSession(os.environ["BCA_CDP_ENDPOINT"])
        capture, inputs = DelayedCapture(session), BrowserInputProvider(session)
        report = {"fault": fault}
        coordinator = target = None
        await session.connect()
        original = {t.target_id for t in await session.list_targets()}
        try:
            with fixture_bundle() as bundle:
                target = await create(session, bundle)
                await session.send(
                    "Emulation.setDeviceMetricsOverride",
                    {"width": 640, "height": 400, "deviceScaleFactor": 1, "mobile": False},
                )
                await capture.start()
                await inputs.start()
                coordinator, facade, bridge = await composition(
                    session, capture, inputs, bundle, tmp_path / "bundle", raw=True, roi=True
                )
                first = await coordinator.refresh()
                assert first.state.status == RecognitionStatus.MATCHED
                old = facade.last_batch
                if fault == "navigate":
                    await session.send("Page.navigate", {"url": "about:blank"})
                    await asyncio.sleep(0.1)
                elif fault == "target_closed":
                    await session.connection.send("Target.closeTarget", {"targetId": target})
                    await asyncio.sleep(0.1)
                    target = None
                else:
                    capture.delay = True
                    if fault == "capture_timeout":
                        bridge._timeout = 0.05
                if fault == "cancel":
                    task = asyncio.create_task(coordinator.refresh())
                    await asyncio.wait_for(entered.wait(), 5)
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                else:
                    with pytest.raises(VisionError):
                        await coordinator.execute_text("click 123")
                    report["outcome"] = "rejected_by_exception"
                    report["status"] = coordinator.latest.state.status.value
                    assert coordinator.latest.state.status != RecognitionStatus.MATCHED
                with pytest.raises((VisionError, BridgeError)):
                    await facade.click(old, "button", 0)
                report["input_outcome"] = bridge.input_outcome
                assert bridge.input_outcome == "not_attempted"
                report["records"] = coordinator.records
                report["close"] = dataclasses.asdict(await coordinator.aclose())
                assert report["close"]["released"]
                coordinator = None
        finally:
            if coordinator is not None:
                report["last_close"] = dataclasses.asdict(await coordinator.aclose())
            await finish(session, capture, inputs, target, original, report)
            (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    entered = None
    asyncio.run(run())
