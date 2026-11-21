"""Owned-page Edge campaign: --endpoint http://127.0.0.1:9341 --samples 30."""

import argparse
import asyncio
import base64
import json
import logging
import platform
import sys
import tracemalloc
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter, process_time
from typing import Any
from urllib.parse import quote

import cv2
import numpy as np

from bca.core.browser import BrowserCaptureProvider, BrowserSession
from bca.core.plugins import (
    FreshnessCaptureAdapter,
    PluginCatalog,
    PluginConfig,
    PluginManager,
    PluginRuntimeHost,
    ProviderLookupView,
)
from bca.core.protocol import Frame
from bca.core.providers import CaptureProvider, ProviderRegistry
from bca.core.runtime import BatchStatus, BrowserFreshness, EventBus, StateStore

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from examples.plugin_integration import (  # noqa: E402
    Composition,
    EvidenceController,
    close_targets,
    evaluate,
    summaries,
)
from examples.plugins.vision_fixture.assets import create_assets  # noqa: E402
from examples.vision_benchmark import memory_bytes  # noqa: E402


def page(root: Path, theme: str) -> str:
    images = [
        "data:image/png;base64,"
        + base64.b64encode((root / f"{state}.{theme}.png").read_bytes()).decode("ascii")
        for state in ("idle", "done")
    ]
    return (
        """<!doctype html><meta charset=utf-8><title>BCA Vision Fixture</title>
<style>html,body{margin:0}body{width:2400px;height:2400px;background:#808080}
img{position:fixed;width:32px;height:24px}#mark{left:80px;top:70px}
#second{left:180px;top:150px;display:none}</style><img id=mark><img id=second>
<script>const images="""
        + json.dumps(images)
        + """;window.hits=0;window.points=[];
mark.src=images[0];second.src=images[0];
for(const el of [mark,second])el.onclick=e=>{hits++;points.push([e.clientX,e.clientY]);
mark.src=images[hits%2];second.src=images[hits%2];};
window.ready=Promise.all([mark.decode(),second.decode()]);</script>"""
    )


class VisionCapture(CaptureProvider):
    def __init__(self, session: BrowserSession) -> None:
        self.browser = BrowserCaptureProvider(session)
        self.region = False
        self.frame: Frame | None = None
        self.last_ms = 0.0

    @property
    def available(self) -> bool:
        return self.browser.available

    async def start(self) -> None:
        await self.browser.start()

    async def close(self) -> None:
        await self.browser.close()

    async def capture(self, page_id: str) -> Frame:
        start = perf_counter()
        frame = (
            await self.browser.capture_region(page_id, x=60, y=50, width=240, height=180)
            if self.region
            else await self.browser.capture(page_id)
        )
        self.last_ms = (perf_counter() - start) * 1000
        self.frame = frame
        return frame


class VisionComposition(Composition):
    def __init__(
        self,
        session: BrowserSession,
        raw: VisionCapture,
        states: StateStore,
        events: EventBus,
        policy: BrowserFreshness,
        theme: str,
    ) -> None:
        self.inputs = policy.create_input_provider()
        self.adapter = FreshnessCaptureAdapter(session, raw, policy)
        registry = ProviderRegistry()
        registry.register(raw)
        registry.register(self.inputs)
        self.view = ProviderLookupView(registry, overrides={"capture": self.adapter})
        self.catalog = PluginCatalog([Path(__file__).resolve().parent / "plugins"])
        self.catalog.discover()
        self.manager = PluginManager(
            self.catalog,
            providers=self.view,
            states=states,
            events=events,
            logger=logging.getLogger("bca.vision.integration"),
        )
        self.manager.load(
            "vision-fixture",
            config=PluginConfig(values={"page_id": session.page_id, "theme": theme}),
        )
        self.states = states
        self.controller = EvidenceController(
            self.manager.observe,
            self.inputs,
            states,
            policy,
            events,
            interval=0.1,
            observation_timeout=15,
        )
        self.host = PluginRuntimeHost(self.manager, self.controller, states)


@asynccontextmanager
async def harness(endpoint: str, *, theme: str = "light") -> Any:
    before_tasks = asyncio.all_tasks()
    session = BrowserSession(endpoint)
    states, events = StateStore(), EventBus()
    raw = VisionCapture(session)
    owned: set[str] = set()
    original: set[str] = set()
    part: VisionComposition | None = None
    evidence: dict[str, Any] = {}
    try:
        await session.connect()
        original = {t.target_id for t in await session.list_targets()}
        target = (await session.connection.send("Target.createTarget", {"url": "about:blank"}))[
            "targetId"
        ]
        assert isinstance(target, str)
        owned.add(target)
        await session.bind(target)
        with TemporaryDirectory(prefix="bca-vision-page-") as directory:
            root = Path(directory)
            create_assets(root)
            html = page(root, theme)
        await session.send("Page.navigate", {"url": "data:text/html," + quote(html)})
        async with asyncio.timeout(10):
            while not await evaluate(session, "typeof ready!=='undefined'"):
                await asyncio.sleep(0.01)
        await evaluate(session, "ready.then(()=>true)")
        await session.send("Page.bringToFront")
        policy = BrowserFreshness(session, states)
        await raw.start()
        part = VisionComposition(session, raw, states, events, policy, theme)
        await part.inputs.start()
        await part.start()
        async with asyncio.timeout(20):
            await states.wait_for_update(0)
        await part.controller.pause()
        yield session, raw, part, states, evidence
    finally:
        try:
            if part is not None:
                await part.close()
                evidence["plugin"] = asdict(part.manager.snapshot())
                evidence["runtime"] = asdict(part.controller.snapshot())
                await part.inputs.close()
        finally:
            await raw.close()
            await states.close()
            await events.close()
            if session.connected:
                await close_targets(session, owned, original)
            await session.close()
            remaining = asyncio.all_tasks() - before_tasks
            evidence["cleanup"] = {
                "pending": session.connection.pending_count,
                "reader": session.connection.reader_running,
                "owned_targets_remaining": 0,
                "remaining_tasks": [t.get_name() for t in remaining],
                "original_targets_preserved": True,
            }
            assert not remaining and not session.connection.pending_count


async def campaign(endpoint: str, output: Path, samples: int = 30) -> dict[str, Any]:
    if samples < 1:
        raise ValueError("samples must be positive")
    output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "status": "running",
        "evidence": "real-browser",
        "endpoint": endpoint,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "opencv": cv2.__version__,
        "samples_per_case": samples,
        "warmup_per_case": 1,
        "records": records,
        "cases": [],
    }
    try:
        for theme in ("light", "dark"):
            async with harness(endpoint, theme=theme) as (session, raw, part, states, evidence):
                report["browser"] = await session.connection.send("Browser.getVersion")
                for dpr in (1, 1.5, 2):
                    await session.send(
                        "Emulation.setDeviceMetricsOverride",
                        {"width": 640, "height": 480, "deviceScaleFactor": dpr, "mobile": False},
                    )
                    await evaluate(
                        session,
                        "new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))",
                    )
                    for region in (False, True):
                        raw.region = region
                        await part.fresh()
                        timings: dict[str, list[float]] = defaultdict(list)
                        wall_start, cpu_start = perf_counter(), process_time()
                        rss_start = memory_bytes()
                        for _ in range(samples):
                            before = states.snapshot()
                            frame = raw.frame
                            assert (
                                before and frame and before.state.source_frame_id == frame.frame_id
                            )
                            assert before.state.data["status"] == "matched"
                            assert before.state.data["variant_id"] == f"panel.{theme}"
                            hits = await evaluate(session, "hits")
                            assert isinstance(hits, int)
                            start = perf_counter()
                            result = await part.host.execute_text("click")
                            assert result.status is BatchStatus.SUCCEEDED
                            await evaluate(
                                session,
                                "Promise.all([mark.decode(),second.decode()]).then(()=>true)",
                            )
                            await part.fresh()
                            timings["host_to_next_commit"].append((perf_counter() - start) * 1000)
                            after = states.snapshot()
                            batch = part.controller.last_batch
                            assert after and batch and batch.observation
                            assert batch.observation.version == before.version
                            action = batch.actions[0]
                            assert action.request_id == result.request_id == batch.request_id
                            assert action.action_id == result.results[0].action_id
                            assert await evaluate(session, "hits") == hits + 1
                            assert after.state.data["asset_id"] != before.state.data["asset_id"]
                            oracle = await evaluate(
                                session,
                                "(()=>{const r=mark.getBoundingClientRect();"
                                "return [r.x+r.width/2,r.y+r.height/2,...points.at(-1)]})()",
                            )
                            assert (
                                isinstance(oracle, list)
                                and action.x is not None
                                and action.y is not None
                            )
                            assert isinstance(oracle[0], (int, float)) and isinstance(
                                oracle[1], (int, float)
                            )
                            error = max(
                                abs(action.x - float(oracle[0])), abs(action.y - float(oracle[1]))
                            )
                            assert error <= 1
                            assert isinstance(oracle[2], (int, float)) and isinstance(
                                oracle[3], (int, float)
                            )
                            dom_error = max(abs(oracle[2] - oracle[0]), abs(oracle[3] - oracle[1]))
                            assert dom_error <= 1
                            for name in (
                                "vision_ms",
                                "decode_ms",
                                "preprocess_ms",
                                "match_ms",
                                "postprocess_ms",
                            ):
                                timings[name].append(float(after.state.data[name]))
                            timings["capture_ms"].append(raw.last_ms)
                            timings["observe_ms"].append(
                                part.controller.snapshot().observation.last_observe_duration_ms
                            )
                            records.append(
                                {
                                    "theme": theme,
                                    "dpr": dpr,
                                    "region": region,
                                    "frame_id": frame.frame_id,
                                    "next_frame_id": after.state.source_frame_id,
                                    "page_id": frame.page_id,
                                    "session_id": frame.session_id,
                                    "request_id": result.request_id,
                                    "batch_id": result.batch_id,
                                    "action_id": action.action_id,
                                    "version": before.version,
                                    "next_version": after.version,
                                    "status": result.status.value,
                                    "css": [action.x, action.y],
                                    "error_css": error,
                                    "dom_css": [oracle[2], oracle[3]],
                                    "dom_error_css": dom_error,
                                    "size": [frame.width, frame.height],
                                    "score": before.state.data["score"],
                                }
                            )
                        report["cases"].append(
                            {
                                "theme": theme,
                                "dpr": dpr,
                                "region": region,
                                "samples": timings,
                                "summary": summaries(timings),
                                "cpu_seconds": process_time() - cpu_start,
                                "wall_seconds": perf_counter() - wall_start,
                                "rss_before": rss_start,
                                "rss_after": memory_bytes(),
                                "template_count": 2,
                                "template_size": [32, 24],
                                "scales": [[1.0, 1.0], [1.5, 1.5], [2.0, 2.0]],
                                "mask": False,
                                "mode": "rgb",
                                "runtime": asdict(part.controller.snapshot()),
                            }
                        )
                if theme == "light" and samples >= 30:
                    # Separate trace run: native RSS and Python tracing have different scopes.
                    before_version = states.version
                    trace_samples = []
                    tracemalloc.start()
                    wall_start, cpu_start = perf_counter(), process_time()
                    await part.controller.resume()
                    for _ in range(15):
                        await asyncio.sleep(1)
                        current, peak = tracemalloc.get_traced_memory()
                        trace_samples.append(
                            {
                                "seconds": perf_counter() - wall_start,
                                "version": states.version,
                                "python_bytes": current,
                                "python_peak_bytes": peak,
                                "rss": memory_bytes(),
                                "tasks": len(asyncio.all_tasks()),
                                "pending_actions": part.controller.snapshot().actions.pending,
                            }
                        )
                    await part.controller.pause()
                    tracemalloc.stop()
                    report["sustained"] = {
                        "samples": trace_samples,
                        "commits": states.version - before_version,
                        "cpu_seconds": process_time() - cpu_start,
                        "wall_seconds": perf_counter() - wall_start,
                        "runtime": asdict(part.controller.snapshot()),
                        "scope": "Python tracemalloc; PSAPI process working set; 15 second run",
                    }
            report.setdefault("lifecycles", []).append(evidence)
        report["status"] = "passed"
    except BaseException as exc:
        report.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        (output / "browser.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--output", type=Path, default=Path(".test-artifacts/04.2/browser"))
    parser.add_argument("--samples", type=int, default=30)
    args = parser.parse_args()
    result = asyncio.run(campaign(args.endpoint, args.output, args.samples))
    print(json.dumps({"status": result["status"], "records": len(result["records"])}))
