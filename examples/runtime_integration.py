"""02.4 reproducible real-image -> real-click -> image-state integration and measurement.

Run: python examples/runtime_integration.py --endpoint http://127.0.0.1:9341
     --output .test-artifacts/02.4-before --samples 5 --duration 10
Instrumentation is confined to this example; no Runtime/Browser monkeypatching.
"""

import argparse
import asyncio
import json
import math
import platform
import tracemalloc
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
from statistics import median
from time import perf_counter
from urllib.parse import quote

from PIL import Image, ImageChops

from bca.core.browser import BrowserCaptureProvider, BrowserInputProvider, BrowserSession
from bca.core.protocol import (
    Action,
    ActionResult,
    ActionType,
    Event,
    Frame,
    JsonObject,
    JsonValue,
    MouseButton,
    PageState,
)
from bca.core.providers import CaptureProvider, InputProvider
from bca.core.runtime import (
    ActionBatch,
    ActionObservationRef,
    BatchStatus,
    BrowserFreshness,
    EventBus,
    RuntimeController,
    StateStore,
)

HTML = """<!doctype html><meta charset=utf-8><title>BCA Runtime Integration</title>
<style>html,body{margin:0}body{width:3000px;height:3000px;background:#eee}
#mark{position:fixed;left:40px;top:40px;width:80px;height:80px;background:#f00}</style>
<div id=mark></div><script>window.hits=0;mark.onclick=()=>{
 hits++;mark.style.background=hits%2?'#00f':'#f00';};</script>"""


class Probe:
    def __init__(self) -> None:
        self.phase: ContextVar[str] = ContextVar("probe_phase", default="setup")
        self.samples: dict[str, list[float]] = defaultdict(list)
        self.requests: Counter[str] = Counter()

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        token = self.phase.set(name)
        start = perf_counter()
        try:
            yield
        finally:
            self.samples[name].append((perf_counter() - start) * 1000)
            self.phase.reset(token)

    def summaries(self) -> JsonObject:
        result: JsonObject = {}
        for name, values in sorted(self.samples.items()):
            if not values:
                continue
            ordered = sorted(values)
            result[name] = {
                "n": len(values),
                "median_ms": median(values),
                "p95_ms": ordered[math.ceil(len(values) * 0.95) - 1],
                "max_ms": max(values),
            }
        return result


class MeasuredSession(BrowserSession):
    def __init__(self, endpoint: str, probe: Probe) -> None:
        super().__init__(endpoint)
        self.probe = probe

    async def send(
        self, method: str, params: JsonObject | None = None, *, timeout: float | None = None
    ) -> JsonObject:
        key = self.probe.phase.get() + "/" + method
        self.probe.requests[key] += 1
        with self.probe.measure("cdp/" + key):
            return await super().send(method, params, timeout=timeout)


class MeasuredCapture(CaptureProvider):
    """Region adapter deliberately requires the concrete Browser extension."""

    def __init__(self, browser: BrowserCaptureProvider, probe: Probe) -> None:
        self.browser, self.probe = browser, probe
        self.region = False

    @property
    def available(self) -> bool:
        return self.browser.available

    async def start(self) -> None:
        await self.browser.start()

    async def close(self) -> None:
        await self.browser.close()

    async def capture(self, page_id: str) -> Frame:
        name = "capture_region" if self.region else "capture_full"
        before = sum(sum(v) for k, v in self.probe.samples.items() if k.startswith("cdp/" + name))
        start = perf_counter()
        with self.probe.measure(name):
            if self.region:
                frame = await self.browser.capture_region(
                    page_id, x=40.25, y=40.25, width=79.25, height=79.25
                )
            else:
                frame = await self.browser.capture(page_id)
        after = sum(sum(v) for k, v in self.probe.samples.items() if k.startswith("cdp/" + name))
        self.probe.samples[name + "_non_cdp"].append(
            (perf_counter() - start) * 1000 - (after - before)
        )
        return frame


class MeasuredInput(InputProvider):
    def __init__(self, browser: BrowserInputProvider, probe: Probe) -> None:
        self.browser, self.probe = browser, probe

    @property
    def available(self) -> bool:
        return self.browser.available

    @property
    def input_state_uncertain(self) -> bool:
        return self.browser.input_state_uncertain

    async def start(self) -> None:
        await self.browser.start()

    async def close(self) -> None:
        await self.browser.close()

    async def execute(self, action: Action) -> ActionResult:
        with self.probe.measure("input"):
            return await self.browser.execute(action)


class MeasuredStore(StateStore):
    def __init__(self, probe: Probe) -> None:
        super().__init__()
        self.probe = probe

    async def publish(self, state: PageState) -> None:
        with self.probe.measure("publish"):
            await super().publish(state)


class MeasuredBus(EventBus):
    def __init__(self, probe: Probe) -> None:
        super().__init__()
        self.probe = probe

    async def emit(self, event: Event) -> None:
        with self.probe.measure("emit"):
            await super().emit(event)


class MeasuredFreshness(BrowserFreshness):
    def __init__(self, session: BrowserSession, states: StateStore, probe: Probe) -> None:
        super().__init__(session, states)
        self.probe = probe

    async def begin(self) -> object:
        with self.probe.measure("freshness_begin"):
            return await super().begin()

    async def validate(self, token: object, state: PageState) -> bool:
        with self.probe.measure("freshness_validate"):
            return await super().validate(token, state)

    async def check(self, reference: ActionObservationRef | None, action: Action) -> bool:
        with self.probe.measure("freshness_action"):
            return await super().check(reference, action)


async def evaluate(session: BrowserSession, expression: str) -> JsonValue:
    value = await session.send(
        "Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True}
    )
    assert "exceptionDetails" not in value
    remote = value.get("result")
    assert isinstance(remote, dict)
    return remote.get("value")


def recognize(frame: Frame) -> tuple[tuple[float, float], bool]:
    """Only actual PNG pixels determine both coordinates and alternating state."""
    with Image.open(BytesIO(frame.data)) as image, image.convert("RGB") as rgb:
        red, green, blue = rgb.split()
        try:
            for channel, other, selected in ((red, blue, False), (blue, red, True)):
                with (
                    channel.point(lambda v: 255 if v > 240 else 0) as high,
                    other.point(lambda v: 255 if v < 15 else 0) as low,
                    green.point(lambda v: 255 if v < 15 else 0) as dark,
                    ImageChops.multiply(high, low) as first,
                    ImageChops.multiply(first, dark) as mask,
                ):
                    bounds = mask.getbbox()
                if bounds:
                    x0, y0, x1, y1 = bounds
                    return frame.pixel_to_css((x0 + x1 - 1) / 2, (y0 + y1 - 1) / 2), selected
        finally:
            red.close()
            green.close()
            blue.close()
    raise AssertionError("fixture marker absent from real screenshot")


async def run_integration(
    endpoint: str, output: Path, *, samples: int = 5, duration: float = 10
) -> JsonObject:
    if samples < 1 or duration < 0:
        raise ValueError("invalid sample configuration")
    output.mkdir(parents=True, exist_ok=True)
    probe = Probe()
    session = MeasuredSession(endpoint, probe)
    states, bus = MeasuredStore(probe), MeasuredBus(probe)
    policy = MeasuredFreshness(session, states, probe)
    capture = MeasuredCapture(BrowserCaptureProvider(session), probe)
    inputs = MeasuredInput(BrowserInputProvider(session), probe)
    target: str | None = None
    original: set[str] = set()
    controller: RuntimeController | None = None
    events: list[Event] = []
    resource_samples: list[JsonValue] = []
    records: list[JsonValue] = []
    checks: list[JsonValue] = []
    tasks_before = asyncio.all_tasks()
    report: JsonObject = {
        "status": "running",
        "evidence": "real-browser",
        "python": platform.python_version(),
        "samples_per_case": samples,
        "duration_seconds": duration,
        "records": records,
        "checks": checks,
        "resource_samples": resource_samples,
    }
    subscription = bus.subscribe(max_queue_size=64)

    async def drain() -> None:
        while (event := await subscription.get()) is not None:
            events.append(event)

    drain_task = asyncio.create_task(drain(), name="example-event-drain")
    monitor_task: asyncio.Task[None] | None = None
    last_frame: Frame | None = None
    active = peak = 0
    starts: list[float] = []
    sustained = False

    async def observe() -> PageState:
        nonlocal last_frame, active, peak
        active += 1
        peak = max(peak, active)
        if sustained:
            starts.append(perf_counter())
        try:
            with probe.measure("observe"):
                last_frame = await policy.capture(capture)
                with probe.measure("recognize"):
                    point, blue = recognize(last_frame)
                return PageState(
                    plugin_id="pixel-fixture",
                    sequence=states.version,
                    source_frame_id=last_frame.frame_id,
                    data={"x": point[0], "y": point[1], "blue": blue},
                )
        finally:
            active -= 1

    async def fresh() -> None:
        assert controller is not None
        version = states.version
        await controller.resume()
        controller.scheduler.request_immediate()
        async with asyncio.timeout(15):
            await states.wait_for_update(version)
        await controller.pause()

    def batch() -> ActionBatch:
        assert controller is not None and target is not None
        snapshot = states.snapshot()
        assert snapshot is not None
        x, y = snapshot.state.data["x"], snapshot.state.data["y"]
        assert isinstance(x, (float, int)) and isinstance(y, (float, int))
        return ActionBatch(
            actions=(
                Action(
                    page_id=target, type=ActionType.MOUSE_CLICK, x=x, y=y, button=MouseButton.LEFT
                ),
            ),
            observation=controller.reference(),
        )

    try:
        tracemalloc.start()
        await session.connect()
        connection = session.connection
        report["browser"] = await connection.send("Browser.getVersion")
        original = {t.target_id for t in await session.list_targets()}
        created = await connection.send("Target.createTarget", {"url": "about:blank"})
        raw = created.get("targetId")
        assert isinstance(raw, str)
        target = raw
        await session.bind(target)
        await session.send("Page.bringToFront")

        async def navigate() -> None:
            await session.send("Page.navigate", {"url": "data:text/html," + quote(HTML)})
            async with asyncio.timeout(10):
                while not await evaluate(session, "typeof hits==='number'"):
                    await asyncio.sleep(0.01)

        await navigate()
        await capture.start()
        await inputs.start()
        controller = RuntimeController(observe, inputs, states, policy, bus, interval=0.1)
        await controller.start()
        async with asyncio.timeout(15):
            await states.wait_for_update(0)
        await controller.pause()

        async def monitor() -> None:
            while True:
                current, memory_peak = tracemalloc.get_traced_memory()
                resource_samples.append(
                    {
                        "time": perf_counter(),
                        "python_bytes": current,
                        "python_peak_bytes": memory_peak,
                        "pending": connection.pending_count,
                        "queue": controller.snapshot().actions.pending if controller else 0,
                        "tasks": len(asyncio.all_tasks()),
                        "observe_active": active,
                    }
                )
                await asyncio.sleep(0.1)

        monitor_task = asyncio.create_task(monitor(), name="example-resource-monitor")
        for dpr in (1, 1.5, 2):
            await session.send(
                "Emulation.setDeviceMetricsOverride",
                {"width": 640, "height": 480, "deviceScaleFactor": dpr, "mobile": False},
            )
            await evaluate(
                session, "new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))"
            )
            for region in (False, True):
                capture.region = region
                await fresh()
                for sample in range(samples):
                    assert last_frame is not None
                    frame = last_frame
                    assert abs(frame.viewport.device_scale_factor - dpr) < 1e-6
                    assert abs(frame.width - frame.viewport.capture_width * dpr) <= 1
                    assert abs(frame.height - frame.viewport.capture_height * dpr) <= 1
                    old = states.snapshot()
                    assert old is not None
                    request = batch()
                    before_hits = await evaluate(session, "hits")
                    assert isinstance(before_hits, int)
                    with probe.measure("submit_to_new_state"):
                        result = await controller.submit(request)
                        assert result.status is BatchStatus.SUCCEEDED
                        await fresh()
                    after = states.snapshot()
                    assert after is not None and after.version > old.version
                    hits = await evaluate(session, "hits")
                    assert hits == before_hits + 1
                    assert after.state.data["blue"] == bool((before_hits + 1) % 2)
                    assert after.state.data["blue"] != old.state.data["blue"]
                    probe.samples["queue_wait"].append(
                        controller.snapshot().actions.last_queue_wait_ms
                    )
                    records.append(
                        {
                            "dpr": dpr,
                            "region": region,
                            "sample": sample,
                            "frame_id": frame.frame_id,
                            "next_frame_id": after.state.source_frame_id,
                            "version": old.version,
                            "next_version": after.version,
                            "batch_id": result.batch_id,
                            "action_id": result.results[0].action_id,
                            "page_id": target,
                            "session_id": session.session_id,
                            "css": [request.actions[0].x, request.actions[0].y],
                            "hits": hits,
                            "blue": after.state.data["blue"],
                        }
                    )
                    if sample == 0:
                        (output / f"dpr-{dpr}-region-{region}.png").write_bytes(frame.data)
        # Mutations happen while paused; an old batch must never produce input.
        for change in ("scroll", "resize", "navigate", "rebind"):
            request = batch()
            if change == "scroll":
                await evaluate(session, "scrollTo(100,100)")
            elif change == "resize":
                await session.send(
                    "Emulation.setDeviceMetricsOverride",
                    {"width": 700, "height": 500, "deviceScaleFactor": 2, "mobile": False},
                )
            elif change == "navigate":
                await navigate()
            else:
                await session.unbind()
                await session.bind(target)
            result = await controller.submit(request)
            assert result.status is BatchStatus.STALE and not result.results
            await fresh()
            result = await controller.submit(batch())
            assert result.status is BatchStatus.SUCCEEDED
            await fresh()
            checks.append({"change": change, "old": "stale", "new": "succeeded"})
        capture.region = False
        await fresh()
        sustained = True
        await controller.resume()
        for _ in range(20):
            controller.scheduler.request_immediate()
        await asyncio.sleep(duration)
        await controller.pause()
        sustained = False
        probe.samples["observation_interval"] = [
            (b - a) * 1000 for a, b in zip(starts, starts[1:], strict=False)
        ]
        # A slow subscriber times out notifications without rolling back committed states.
        slow = bus.subscribe(max_queue_size=1)
        await fresh()
        await fresh()
        assert controller.snapshot().observation.event_emit_failed >= 1
        await slow.close()
        assert any(
            e.type == "runtime.observation_completed" and e.data.get("version") == 1 for e in events
        )
        assert all(
            any(
                e.type == "runtime.action_completed" and e.data.get("batch_id") == r["batch_id"]
                for e in events
            )
            for r in records
            if isinstance(r, dict)
        )
        assert all(
            any(
                e.type == "runtime.observation_completed"
                and e.data.get("version") == r["next_version"]
                and e.data.get("source_frame_id") == r["next_frame_id"]
                for e in events
            )
            for r in records
            if isinstance(r, dict)
        )
        request = batch()
        await connection.send("Target.closeTarget", {"targetId": target})
        async with asyncio.timeout(5):
            while session.is_ready:
                await asyncio.sleep(0.01)
        result = await controller.submit(request)
        assert result.status in (BatchStatus.BLOCKED, BatchStatus.FAILED)
        checks.append({"change": "destroy", "status": result.status.value})
        await controller.stop()
        await controller.stop()
        report["runtime"] = asdict(controller.snapshot())
        report["observe_peak"] = peak
        report["event_count"] = len(events)
        report["status"] = "passed"
    except BaseException as exc:
        report["status"] = "failed"
        report["error_type"] = type(exc).__name__
        raise
    finally:
        errors: list[JsonValue] = []
        if controller is not None:
            await controller.stop()
        if monitor_task is not None:
            monitor_task.cancel()
            await asyncio.gather(monitor_task, return_exceptions=True)
        for name, close in (("input", inputs.close), ("capture", capture.close)):
            try:
                await close()
            except Exception as exc:
                errors.append({"stage": name, "type": type(exc).__name__})
        if session.connected:
            remaining = {t.target_id for t in await session.list_targets()}
            if target in remaining:
                await session.connection.send("Target.closeTarget", {"targetId": target})
            remaining = {t.target_id for t in await session.list_targets()}
            report["owned_targets_remaining"] = int(target in remaining)
            report["original_targets_preserved"] = original.issubset(remaining)
        await session.close()
        await states.close()
        await bus.close()
        await drain_task
        report["cleanup"] = {
            "pending_count": session.connection.pending_count,
            "reader_running": session.connection.reader_running,
            "connected": session.connected,
            "input_state_uncertain": inputs.input_state_uncertain,
            "errors": errors,
            "new_unfinished_tasks": len(asyncio.all_tasks() - tasks_before),
        }
        if (
            report.get("owned_targets_remaining") != 0
            or report.get("original_targets_preserved") is not True
            or session.connection.pending_count
            or session.connection.reader_running
            or session.connected
            or asyncio.all_tasks() - tasks_before
            or errors
        ):
            report["status"] = "failed"
        report["timing"] = probe.summaries()
        report["raw_ms"] = {key: list(values) for key, values in probe.samples.items()}
        report["cdp_requests"] = dict(probe.requests)
        report["measurement"] = (
            "perf_counter inclusive boundaries; capture_non_cdp is total minus awaited session CDP "
            "(includes PNG decode/CRC/crop/re-encode, Python and instrumentation overhead, "
            "not decode alone). "
            "submit_to_new_state includes submit, resume/immediate and pause completion. "
            "observation_interval only samples the sustained section. tracemalloc measures Python "
            "allocations including retained report samples, not process/native/Edge RSS. "
            "CDP counts cover bound-page Session.send only; setup Target/Browser commands excluded."
        )
        tracemalloc.stop()
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert report["owned_targets_remaining"] == 0 and report["original_targets_preserved"] is True
    assert (
        not errors
        and session.connection.pending_count == 0
        and not session.connection.reader_running
    )
    cleanup = report["cleanup"]
    assert isinstance(cleanup, dict) and cleanup["new_unfinished_tasks"] == 0
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--duration", type=float, default=10)
    args = parser.parse_args()
    report = asyncio.run(
        run_integration(args.endpoint, args.output, samples=args.samples, duration=args.duration)
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(args.output / "report.json"),
                "cleanup": report["cleanup"],
            },
            indent=2,
        )
    )
