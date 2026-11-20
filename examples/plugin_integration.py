"""Opt-in real Edge plugin campaign. Only creates and controls owned test pages.

python /path/to/examples/plugin_integration.py --endpoint http://127.0.0.1:9341
"""

import argparse
import asyncio
import json
import logging
import math
import platform
import tracemalloc
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from statistics import median
from time import perf_counter
from urllib.parse import quote

from bca.core.browser import BrowserCaptureProvider, BrowserSession
from bca.core.plugins import (
    FreshnessCaptureAdapter,
    PluginCatalog,
    PluginConfig,
    PluginManager,
    PluginRuntimeHost,
    ProviderLookupView,
)
from bca.core.protocol import Frame, JsonObject, JsonValue
from bca.core.providers import CaptureProvider, InputProvider, ProviderRegistry
from bca.core.runtime import (
    ActionBatch,
    BatchResult,
    BatchStatus,
    BrowserFreshness,
    EventBus,
    RuntimeController,
    StateStore,
)

ROOT = Path(__file__).resolve().parent
HTML = """<!doctype html><meta charset=utf-8><title>BCA Plugin Integration</title>
<style>html,body{margin:0}body{width:3000px;height:3000px;background:#eee}
#mark{position:fixed;left:40px;top:40px;width:80px;height:80px;background:#f00}
input{position:fixed;left:180px;top:40px}</style><div id=mark></div><input id=field>
<script>window.hits=0;window.down=0;window.keys=0;
document.onmousedown=()=>down++;document.onkeydown=()=>keys++;
mark.onclick=()=>{hits++;mark.style.background=hits%2?'#00f':'#f00';};</script>"""


async def evaluate(session: BrowserSession, expression: str) -> JsonValue:
    result = await session.send(
        "Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True}
    )
    assert "exceptionDetails" not in result
    remote = result.get("result")
    assert isinstance(remote, dict)
    return remote.get("value")


async def navigate(session: BrowserSession) -> None:
    await session.send("Page.navigate", {"url": "data:text/html," + quote(HTML)})
    async with asyncio.timeout(10):
        while not await evaluate(
            session, "typeof hits==='number' && !!document.getElementById('mark')"
        ):
            await asyncio.sleep(0.01)
    await session.send("Page.bringToFront")


class RegionCapture(CaptureProvider):
    """Borrow the concrete Browser region extension; never change the Provider ABC."""

    def __init__(self, browser: BrowserCaptureProvider) -> None:
        self.browser = browser
        self.region = False
        self.frame: Frame | None = None

    @property
    def available(self) -> bool:
        return self.browser.available

    async def start(self) -> None:
        await self.browser.start()

    async def close(self) -> None:
        await self.browser.close()

    async def capture(self, page_id: str) -> Frame:
        if self.region:
            frame = await self.browser.capture_region(
                page_id, x=40.25, y=40.25, width=79.25, height=79.25
            )
        else:
            frame = await self.browser.capture(page_id)
        self.frame = frame
        return frame


class EvidenceController(RuntimeController):
    """Example-only instrumentation at the public submission boundary."""

    last_batch: ActionBatch | None = None

    async def submit(self, batch: ActionBatch) -> BatchResult:
        self.last_batch = batch
        return await super().submit(batch)


class Composition:
    """Explicit owner of host/adapter only. Caller owns Session/raw providers/sinks."""

    def __init__(
        self,
        session: BrowserSession,
        raw: CaptureProvider,
        inputs: InputProvider,
        states: StateStore,
        events: EventBus,
        policy: BrowserFreshness,
        *,
        root: Path = ROOT / "plugins",
        plugin_id: str = "pixel-fixture",
        interval: float = 100,
        observation_timeout: float = 10,
    ) -> None:
        self.adapter = FreshnessCaptureAdapter(session, raw, policy)
        registry = ProviderRegistry()
        registry.register(raw)
        registry.register(inputs)
        self.view = ProviderLookupView(registry, overrides={"capture": self.adapter})
        self.catalog = PluginCatalog([root])
        self.catalog.discover()
        self.manager = PluginManager(
            self.catalog,
            providers=self.view,
            states=states,
            events=events,
            logger=logging.getLogger("bca.plugin.integration"),
        )
        self.manager.load(plugin_id, config=PluginConfig(values={"page_id": session.page_id}))
        self.states = states
        self.controller = EvidenceController(
            self.manager.observe,
            inputs,
            states,
            policy,
            events,
            interval=interval,
            observation_timeout=observation_timeout,
        )
        self.host = PluginRuntimeHost(self.manager, self.controller, states)
        assert self.view.get(InputProvider) is inputs  # type: ignore[type-abstract]

    async def start(self) -> None:
        await self.adapter.start()
        assert self.view.get(CaptureProvider) is self.adapter  # type: ignore[type-abstract]
        await self.host.start()

    async def fresh(self) -> None:
        version = self.states.version
        await self.controller.resume()
        self.controller.scheduler.request_immediate()
        async with asyncio.timeout(15):
            await self.states.wait_for_update(version)
        await self.controller.pause()

    async def close(self) -> None:
        try:
            await self.host.close()
        finally:
            await self.adapter.close()


def summaries(samples: dict[str, list[float]]) -> JsonObject:
    return {
        key: {
            "n": len(values),
            "median_ms": median(values),
            "p95_ms": sorted(values)[math.ceil(len(values) * 0.95) - 1],
            "max_ms": max(values),
        }
        for key, values in samples.items()
        if values
    }


async def close_targets(owner: BrowserSession, owned: set[str], original: set[str]) -> None:
    remaining = {t.target_id for t in await owner.list_targets()}
    for target in owned & remaining:
        await owner.connection.send("Target.closeTarget", {"targetId": target})
    async with asyncio.timeout(5):
        while True:
            remaining = {t.target_id for t in await owner.list_targets()}
            if not owned & remaining:
                break
            await asyncio.sleep(0.01)
    assert original <= remaining


async def run_integration(
    endpoint: str, output: Path, *, samples: int = 3, duration: float = 3
) -> JsonObject:
    if samples < 1 or duration < 0:
        raise ValueError("invalid sample configuration")
    output.mkdir(parents=True, exist_ok=True)
    tasks_before = asyncio.all_tasks()
    session = BrowserSession(endpoint)
    states, events = StateStore(), EventBus()
    raw = RegionCapture(BrowserCaptureProvider(session))
    policy = BrowserFreshness(session, states)
    inputs = None
    part = None
    owned: set[str] = set()
    original: set[str] = set()
    records: list[JsonValue] = []
    checks: list[JsonValue] = []
    timings: dict[str, list[float]] = defaultdict(list)
    resources: list[JsonValue] = []
    report: JsonObject = {
        "evidence": "real-browser",
        "status": "running",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "endpoint": endpoint,
        "records": records,
        "checks": checks,
        "resource_samples": resources,
        "samples_per_case": samples,
        "duration_seconds": duration,
    }
    trace_owned = not tracemalloc.is_tracing()
    if trace_owned:
        tracemalloc.start()

    def resource(stage: str) -> None:
        current, peak = tracemalloc.get_traced_memory()
        resources.append(
            {
                "stage": stage,
                "python_bytes": current,
                "python_peak_bytes": peak,
                "tasks": len(asyncio.all_tasks()),
                "pending": session.connection.pending_count,
                "queue": part.controller.snapshot().actions.pending if part else 0,
            }
        )

    try:
        await session.connect()
        version = await session.connection.send("Browser.getVersion")
        report["browser"] = version.get("product")
        report["edge_processes_before"] = await session.connection.send("SystemInfo.getProcessInfo")
        original = {t.target_id for t in await session.list_targets()}
        created = await session.connection.send("Target.createTarget", {"url": "about:blank"})
        target = created["targetId"]
        assert isinstance(target, str)
        owned.add(target)
        await session.bind(target)
        await navigate(session)
        await session.send("Performance.enable")
        report["renderer_metrics_before"] = await session.send("Performance.getMetrics")
        await raw.start()
        inputs = policy.create_input_provider()
        await inputs.start()
        part = Composition(session, raw, inputs, states, events, policy, interval=0.1)
        resource("before_start")
        started = perf_counter()
        await part.start()
        async with asyncio.timeout(15):
            await states.wait_for_update(0)
        timings["start_to_first_commit"].append((perf_counter() - started) * 1000)
        await part.controller.pause()
        assert states.version == 1 and part.controller.reference() is not None
        report["plugin"] = asdict(part.manager.snapshot())
        for dpr in (1, 1.5, 2):
            await session.send(
                "Emulation.setDeviceMetricsOverride",
                {"width": 640, "height": 480, "deviceScaleFactor": dpr, "mobile": False},
            )
            await evaluate(
                session, "new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))"
            )
            for region in (False, True):
                raw.region = region
                await part.fresh()
                for index in range(samples):
                    before = states.snapshot()
                    frame = raw.frame
                    assert before is not None and frame is not None
                    assert before.state.source_frame_id == frame.frame_id
                    assert abs(frame.viewport.device_scale_factor - dpr) < 1e-6
                    assert abs(frame.width - frame.viewport.capture_width * dpr) <= 1
                    assert abs(frame.height - frame.viewport.capture_height * dpr) <= 1
                    assert 40 <= before.state.data["x"] < 120  # type: ignore[operator]
                    assert 40 <= before.state.data["y"] < 120  # type: ignore[operator]
                    hits = await evaluate(session, "hits")
                    assert isinstance(hits, int)
                    start = perf_counter()
                    result = await part.host.execute_text("click")
                    timings["execute_text"].append((perf_counter() - start) * 1000)
                    assert result.status is BatchStatus.SUCCEEDED
                    batch = part.controller.last_batch
                    assert batch is not None and batch.observation is not None
                    assert batch.observation.version == before.version
                    assert batch.request_id == result.request_id == batch.actions[0].request_id
                    assert batch.actions[0].action_id == result.results[0].action_id
                    await part.fresh()
                    timings["command_to_verified_commit"].append((perf_counter() - start) * 1000)
                    after = states.snapshot()
                    assert after is not None and after.version == before.version + 1
                    assert after.state.sequence == before.state.sequence + 1
                    assert after.state.data["blue"] != before.state.data["blue"]
                    assert await evaluate(session, "hits") == hits + 1
                    assert after.state.data["blue"] == bool((hits + 1) % 2)
                    stats = part.controller.snapshot()
                    timings["observation_through_publish"].append(
                        stats.observation.last_observe_duration_ms
                        + stats.observation.last_publish_duration_ms
                    )
                    timings["queue"].append(stats.actions.last_queue_wait_ms)
                    timings["input_and_authorization"].append(stats.actions.last_execution_ms)
                    records.append(
                        {
                            "dpr": dpr,
                            "region": region,
                            "version": before.version,
                            "next_version": after.version,
                            "frame_id": frame.frame_id,
                            "next_frame_id": after.state.source_frame_id,
                            "request_id": result.request_id,
                            "action_request_id": batch.actions[0].request_id,
                            "batch_id": result.batch_id,
                            "action_id": result.results[0].action_id,
                            "status": result.status.value,
                            "hits": hits + 1,
                            "before_blue": before.state.data["blue"],
                            "after_blue": after.state.data["blue"],
                            "page_id": target,
                            "css": [before.state.data["x"], before.state.data["y"]],
                        }
                    )
                    if index == 0:
                        (output / f"dpr-{dpr}-region-{region}.png").write_bytes(frame.data)
                    resource("click")
        for change in ("scroll", "resize", "navigate", "reload", "rebind"):
            if change == "scroll":
                await evaluate(session, "scrollTo(100,100)")
                await evaluate(session, "new Promise(r=>requestAnimationFrame(r))")
            elif change == "resize":
                await session.send(
                    "Emulation.setDeviceMetricsOverride",
                    {"width": 700, "height": 500, "deviceScaleFactor": 2, "mobile": False},
                )
            elif change == "navigate":
                await navigate(session)
            elif change == "reload":
                origin = await evaluate(session, "performance.timeOrigin")
                await session.send("Page.reload")
                async with asyncio.timeout(10):
                    while (await evaluate(session, "performance.timeOrigin")) == origin:
                        await asyncio.sleep(0.01)
                    while not await evaluate(session, "typeof hits==='number'"):
                        await asyncio.sleep(0.01)
            else:
                await session.unbind()
                await session.bind(target)
                await session.send("Performance.enable")
            hits = await evaluate(session, "hits")
            result = await part.host.execute_text("click")
            assert result.status is BatchStatus.STALE and not result.results
            assert await evaluate(session, "hits") == hits
            await part.fresh()
            result = await part.host.execute_text("click")
            assert result.status is BatchStatus.SUCCEEDED
            await part.fresh()
            checks.append({"change": change, "old": "stale", "new": result.status.value})
        raw.region = False
        await part.fresh()
        count = states.version
        started = perf_counter()
        await part.controller.resume()
        while perf_counter() - started < duration:
            resource("sustained")
            await asyncio.sleep(0.1)
        await part.controller.pause()
        report["sustained"] = {
            "seconds": perf_counter() - started,
            "observations": states.version - count,
            "clicks": 0,
        }
        renderer_metrics = await session.send("Performance.getMetrics")
        assert renderer_metrics["metrics"]
        report["renderer_metrics_after"] = renderer_metrics
        report["edge_processes_after"] = await session.connection.send("SystemInfo.getProcessInfo")
        await session.connection.send("Target.closeTarget", {"targetId": target})
        async with asyncio.timeout(5):
            while session.is_ready:
                await asyncio.sleep(0.01)
        result = await part.host.execute_text("click")
        assert result.status is BatchStatus.BLOCKED
        checks.append({"change": "target_closed", "status": result.status.value})
        report["status"] = "passed"
    except BaseException as exc:
        report["status"] = "failed"
        report["error_type"] = type(exc).__name__
        raise
    finally:
        errors: list[JsonValue] = []
        # Continue independent owner cleanup even if a plugin stop callback fails.
        if part is not None:
            try:
                await part.close()
            except BaseException as exc:
                errors.append({"stage": "host", "type": type(exc).__name__})
            report["plugin_final"] = asdict(part.manager.snapshot())
            report["runtime"] = asdict(part.controller.snapshot())
            if part.manager.snapshot().cleanup_status != "succeeded":
                errors.append({"stage": "plugin", "type": part.manager.snapshot().cleanup_error})
        for name, component in (("input", inputs), ("capture", raw)):
            if component is not None:
                try:
                    await component.close()
                except Exception as exc:
                    errors.append({"stage": name, "type": type(exc).__name__})
        try:
            if session.connected:
                await close_targets(session, owned, original)
                report["owned_targets_remaining"] = 0
                report["original_targets_preserved"] = True
        finally:
            await session.close()
            await states.close()
            await events.close()
        resource("after_close")
        report["cleanup"] = {
            "errors": errors,
            "pending_count": session.connection.pending_count,
            "reader_running": session.connection.reader_running,
            "connected": session.connected,
            "new_unfinished_tasks": len(asyncio.all_tasks() - tasks_before),
        }
        if (
            errors
            or session.connection.pending_count
            or session.connection.reader_running
            or asyncio.all_tasks() - tasks_before
        ):
            report["status"] = "failed"
        report["timing"] = summaries(timings)
        report["raw_ms"] = {key: list(values) for key, values in timings.items()}
        report["measurement"] = (
            "Inclusive perf_counter/Runtime timings; command-to-commit includes resume/pause "
            "and PNG recognition, "
            "excludes DOM oracle and disk writes. No isolated parse/generate timing. "
            "Queue/input timings from Runtime; "
            "input includes freshness checks. tracemalloc covers Python only, not native/Edge RSS. "
            "Resource samples include accumulated report data. "
            "Sustained section observes without clicks; "
            "serial command section is not a queue saturation benchmark. "
            "No equivalence to BCA-02 timings claimed."
        )
        if trace_owned:
            tracemalloc.stop()
        (output / "plugin-integration-report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
    assert report["status"] == "passed"
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--output", type=Path, default=Path(".test-artifacts/03.2/example"))
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--duration", type=float, default=3)
    args = parser.parse_args()
    result = asyncio.run(
        run_integration(args.endpoint, args.output, samples=args.samples, duration=args.duration)
    )
    print(json.dumps({"status": result["status"], "cleanup": result["cleanup"]}, indent=2))
