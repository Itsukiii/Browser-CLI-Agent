"""Screenshot -> Action -> DOM acceptance, only on a target created by this example."""

import argparse
import asyncio
import json
import math
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from statistics import median
from time import perf_counter
from urllib.parse import quote

from PIL import Image

from bca.core.browser import (
    BrowserCaptureProvider,
    BrowserInputProvider,
    BrowserSession,
    CDPConnection,
    TargetLostError,
)
from bca.core.browser.geometry import Geometry, measure_geometry
from bca.core.errors import ValidationError
from bca.core.protocol import (
    Action,
    ActionResult,
    ActionStatus,
    ActionType,
    Frame,
    JsonObject,
    JsonValue,
    MouseButton,
    to_dict,
)
from bca.core.providers import CaptureProvider, InputProvider, ProviderRegistry

HTML = """<!doctype html><meta charset=utf-8><title>BCA End to End</title>
<style>html,body{margin:0}body{width:3000px;height:3000px;background:#eee}
#mark{position:fixed;left:40px;top:40px;width:80px;height:80px;background:#f00}
#count{position:fixed;left:200px;top:40px}</style>
<div id=mark></div><output id=count>0</output><script>
window.hits=[];document.addEventListener('click',e=>{
hits.push({target:e.target.id,x:e.clientX,y:e.clientY});
document.getElementById('count').textContent=hits.length;
});</script>"""


async def evaluate(session: BrowserSession, expression: str) -> JsonValue:
    result = await session.send(
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        },
    )
    if "exceptionDetails" in result:
        raise AssertionError("controlled fixture evaluation failed")
    remote = result.get("result")
    assert isinstance(remote, dict)
    return remote.get("value")


def identity(session: BrowserSession) -> tuple[CDPConnection, str | None, str | None, int]:
    return session.connection, session.page_id, session.session_id, session.generation


@dataclass(frozen=True)
class Observation:
    """Example-owned context, not an extension to the public Frame protocol."""

    frame: Frame
    binding: tuple[CDPConnection, str | None, str | None, int]
    geometry: Geometry


async def observe(session: BrowserSession, registry: ProviderRegistry, region: bool) -> Observation:
    binding = identity(session)
    page = session.page_id
    assert page is not None
    before = await measure_geometry(session)
    if region:
        # Region capture is a Browser extension, not part of the CaptureProvider ABC.
        frame = await registry.get(BrowserCaptureProvider).capture_region(
            page, x=40.25, y=40.25, width=79.25, height=79.25
        )
    else:
        frame = await registry.get(CaptureProvider).capture(page)  # type: ignore[type-abstract]
    after = await measure_geometry(session)
    if not session.is_ready or binding != identity(session) or before != after:
        raise TargetLostError("observation context changed; observe again")
    return Observation(frame, binding, after)


def red_center(frame: Frame) -> tuple[float, float]:
    """Decision is derived only from decoded PNG bytes, never DOM element geometry."""
    with Image.open(BytesIO(frame.data)) as image:
        assert image.size == (frame.width, frame.height)
        with image.convert("RGB") as rgb:
            # Threshold bands also reject gray/white background and antialiasing.
            r, g, b = rgb.split()
            from PIL import ImageChops

            mask = ImageChops.multiply(
                r.point(lambda v: 255 if v > 240 else 0),
                ImageChops.multiply(
                    g.point(lambda v: 255 if v < 15 else 0), b.point(lambda v: 255 if v < 15 else 0)
                ),
            )
            bounds = mask.getbbox()
            r.close()
            g.close()
            b.close()
            mask.close()
    if bounds is None:
        raise ValidationError("fixture marker was not found in screenshot")
    left, top, right, bottom = bounds
    return (left + right - 1) / 2, (top + bottom - 1) / 2


async def click_observation(
    session: BrowserSession, registry: ProviderRegistry, observation: Observation
) -> tuple[ActionResult, tuple[float, float]]:
    def check() -> None:
        if not session.is_ready or observation.binding != identity(session):
            raise TargetLostError("stale observation binding; observe again")

    check()
    current = await measure_geometry(session)
    check()
    if current != observation.geometry:
        raise ValidationError("document or viewport changed after observation; observe again")
    point = observation.frame.pixel_to_css(*red_center(observation.frame))
    result = await registry.get(InputProvider).execute(  # type: ignore[type-abstract]
        Action(
            page_id=observation.frame.page_id,
            type=ActionType.MOUSE_CLICK,
            x=point[0],
            y=point[1],
            button=MouseButton.LEFT,
        )
    )
    # DOM can still change between the check and input: this is not an atomic transaction.
    return result, point


async def run_end_to_end(endpoint: str, output: Path, *, samples: int = 3) -> JsonObject:
    if samples < 1:
        raise ValidationError("samples must be positive")
    output.mkdir(parents=True, exist_ok=True)
    session = BrowserSession(endpoint)
    capture, inputs = BrowserCaptureProvider(session), BrowserInputProvider(session)
    registry = ProviderRegistry()
    owned: list[str] = []
    original: set[str] = set()
    records: list[JsonValue] = []
    report: JsonObject = {
        "status": "running",
        "stage": "connect",
        "observations": records,
        "measurement": (
            "perf_counter around observe and click_observation; includes freshness checks "
            "and PNG localization; excludes DOM verification and disk IO"
        ),
    }

    async def cleanup() -> None:
        errors: list[JsonValue] = []
        for name, close in [("input", inputs.close), ("capture", capture.close)]:
            try:
                await close()
            except Exception as exc:
                errors.append({"stage": name, "type": type(exc).__name__})
        report["session_ready_after_providers_close"] = session.is_ready
        try:
            for target in owned:
                try:
                    await session.connection.send("Target.closeTarget", {"targetId": target})
                except Exception as exc:
                    errors.append({"stage": "target_close", "type": type(exc).__name__})
            if session.connected:
                remaining = {t.target_id for t in await session.list_targets()}
                report["owned_targets_remaining"] = [
                    str(t) for t in sorted(remaining.intersection(owned))
                ]
                report["preexisting_targets_preserved"] = original.issubset(remaining)
                if remaining.intersection(owned) or not original.issubset(remaining):
                    errors.append({"stage": "target_ownership", "type": "AssertionError"})
        finally:
            await session.close()
            report["cleanup"] = {
                "pending_count": session.connection.pending_count,
                "reader_running": session.connection.reader_running,
                "connected": session.connected,
                "errors": errors,
            }
        if errors:
            report["status"] = "failed"
            raise AssertionError("integration cleanup failed; inspect report")

    try:
        await session.connect()
        report["browser"] = await session.connection.send("Browser.getVersion")
        original = {t.target_id for t in await session.list_targets()}
        report["existing_target_ids"] = [
            str(t) for t in sorted(original)
        ]  # No user URLs/titles in report.
        report["stage"] = "create_and_bind"
        created = await session.connection.send(
            "Target.createTarget", {"url": "data:text/html;charset=utf-8," + quote(HTML)}
        )
        target = created.get("targetId")
        assert isinstance(target, str)
        owned.append(target)
        report["created_target_id"] = target
        await session.bind(target)  # Explicitly bind only our newly created target.
        await session.send("Page.bringToFront")
        async with asyncio.timeout(10):
            while not await evaluate(session, "typeof hits==='object'"):
                await asyncio.sleep(0.01)
        await session.refresh_target()
        await capture.start()
        await inputs.start()
        registry.register(capture)
        registry.register(inputs)
        report["capabilities"] = list(registry.capabilities)
        report["stage"] = "capture_action_dom"
        for width, height, dpr in [(640, 480, 1), (720, 540, 1.5), (800, 600, 2)]:
            await session.send(
                "Emulation.setDeviceMetricsOverride",
                {"width": width, "height": height, "deviceScaleFactor": dpr, "mobile": False},
            )
            await evaluate(session, "scrollTo(80,120)")
            await evaluate(
                session, "new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))"
            )
            for region in (False, True):
                for sample in range(samples):
                    start = perf_counter()
                    observed = await observe(session, registry, region)
                    capture_ms = (perf_counter() - start) * 1000
                    frame = observed.frame
                    # Check actual raster-to-CSS scale, independently on both axes.
                    assert abs(frame.width - frame.viewport.capture_width * dpr) <= 1
                    assert abs(frame.height - frame.viewport.capture_height * dpr) <= 1
                    assert math.isclose(frame.viewport.device_scale_factor, dpr, rel_tol=1e-6)
                    assert frame.viewport.scroll_x == 80 and frame.viewport.scroll_y == 120
                    assert frame.viewport.width < width and frame.viewport.height < height
                    start = perf_counter()
                    result, point = await click_observation(session, registry, observed)
                    input_ms = (perf_counter() - start) * 1000
                    record: JsonObject = {
                        "frame": to_dict(frame),
                        "generation": observed.binding[3],
                        "region": region,
                        "pixel": list(red_center(frame)),
                        "css": list(point),
                        "action_result": to_dict(result),
                        "capture_ms": capture_ms,
                        "input_ms": input_ms,
                    }
                    records.append(record)  # Preserve evidence before DOM assertions.
                    assert result.status is ActionStatus.SUCCEEDED
                    dom = await evaluate(session, "({hit:hits.at(-1),count:hits.length})")
                    record["dom"] = dom
                    assert isinstance(dom, dict) and isinstance(dom["hit"], dict)
                    hit = dom["hit"]
                    assert hit["target"] == "mark" and dom["count"] == len(records)
                    assert isinstance(hit["x"], (int, float)) and isinstance(hit["y"], (int, float))
                    dx, dy = hit["x"] - point[0], hit["y"] - point[1]
                    record["error_css"] = [dx, dy]
                    assert abs(dx) < 1 and abs(dy) < 1
                    if sample == 0:
                        filename = f"dpr{dpr}-{'region' if region else 'full'}.png"
                        (output / filename).write_bytes(frame.data)
                        record["file"] = filename
        timings: JsonObject = {}
        for key in ("capture_ms", "input_ms"):
            values = [v for r in records if isinstance(r, dict) and isinstance(v := r[key], float)]
            timings[key] = {
                "count": len(values),
                "median": median(values),
                "samples": [float(v) for v in values],
            }
        report["timings"] = timings
        report["status"], report["stage"] = "passed", "complete"
    except BaseException as exc:
        report["status"], report["failure_type"] = "failed", type(exc).__name__
        raise
    finally:
        # Retain the task and finish cleanup even if cancellation is repeated while exiting.
        task = asyncio.create_task(cleanup(), name="bca-example-cleanup")
        cancelled = False
        try:
            while True:
                try:
                    await asyncio.shield(task)
                    break
                except asyncio.CancelledError:
                    cancelled = True
            if cancelled:
                report["status"], report["failure_type"] = "failed", "CancelledError"
                raise asyncio.CancelledError
        finally:
            (output / "browser-integration-report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.environ.get("BCA_CDP_ENDPOINT"))
    parser.add_argument("--output", type=Path, default=Path("browser-artifacts"))
    parser.add_argument("--samples", type=int, default=3)
    args = parser.parse_args()
    if not args.endpoint:
        parser.error("--endpoint or BCA_CDP_ENDPOINT is required")
    report = asyncio.run(run_end_to_end(args.endpoint, args.output, samples=args.samples))
    print(
        json.dumps(
            {
                "status": report["status"],
                "timings": report["timings"],
                "cleanup": report["cleanup"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
