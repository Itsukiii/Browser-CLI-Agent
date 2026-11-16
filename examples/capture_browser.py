"""User-run capture acceptance: creates only disposable targets; never starts a browser."""

import argparse
import asyncio
import json
import math
import os
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from statistics import median
from time import perf_counter
from urllib.parse import quote

from PIL import Image

from bca.core.browser import BrowserCaptureProvider, BrowserError, BrowserSession, CDPTimeoutError
from bca.core.errors import CapabilityUnavailableError
from bca.core.protocol import Frame, JsonObject, JsonValue, to_dict
from bca.core.providers import ProviderRegistry

HTML = """<!doctype html><meta charset=utf-8><title>BCA Capture Grid</title>
<style>html,body{margin:0}body{height:3000px;width:3000px;background:repeating-linear-gradient(
0deg,#eee 0px,#eee 49px,#888 50px)}#mark{position:fixed;left:40px;top:40px;
width:80px;height:80px;background:rgb(255,0,0)}canvas{position:fixed;left:150px;top:40px}
</style><div id=mark></div><div id=edge style="position:fixed;width:20px;height:20px;
background:rgb(255,0,255)"></div><canvas id=c width=80 height=80></canvas>
<script>window.paint=function(color){let ctx=document.getElementById('c').getContext('2d');
ctx.fillStyle=color;ctx.fillRect(0,0,80,80)};paint('rgb(0,0,255)')</script>"""


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
        raise AssertionError(f"fixture evaluation failed: {result['exceptionDetails']}")
    remote = result.get("result")
    assert isinstance(remote, dict), result
    return remote.get("value")


def assert_color(frame: Frame, x: float, y: float, color: tuple[int, int, int]) -> None:
    v = frame.viewport
    px = int((x - v.capture_x) * frame.width / v.capture_width)
    py = int((y - v.capture_y) * frame.height / v.capture_height)
    assert 0 <= px < frame.width and 0 <= py < frame.height
    with Image.open(BytesIO(frame.data)) as image:
        image.load()
        assert image.size == (frame.width, frame.height)
        with image.convert("RGB") as rgb:
            assert rgb.getpixel((px, py)) == color, (x, y, rgb.getpixel((px, py)), color)


async def geometry_evidence(session: BrowserSession) -> JsonObject:
    """Bounded numeric diagnostics, kept even if the first screenshot fails."""
    metrics = await session.send("Page.getLayoutMetrics")
    evidence: JsonObject = {}
    for name in ("cssVisualViewport", "cssLayoutViewport"):
        raw = metrics.get(name)
        evidence[name] = {
            key: value
            for key in (
                "clientWidth",
                "clientHeight",
                "pageX",
                "pageY",
                "offsetX",
                "offsetY",
                "scale",
                "zoom",
            )
            if isinstance(raw, dict)
            and isinstance(value := raw.get(key), (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        }
    evidence["dom"] = await evaluate(
        session,
        """(() => {
        const v=visualViewport, d=document.documentElement;
        const w=Math.min(v.width,d.clientWidth), h=Math.min(v.height,d.clientHeight);
        const edge=document.getElementById('edge');
        edge.style.left=(w-30)+'px'; edge.style.top=(h-30)+'px';
        return {width:w,height:h,clientWidth:d.clientWidth,clientHeight:d.clientHeight,
                visualWidth:v.width,visualHeight:v.height,dpr:devicePixelRatio,
                surfaceWidth:innerWidth,surfaceHeight:innerHeight,
                scrollX:scrollX,scrollY:scrollY}; })()""",
    )
    visual, layout = evidence["cssVisualViewport"], evidence["cssLayoutViewport"]
    if isinstance(visual, dict) and isinstance(layout, dict):
        zoom, x, y = visual.get("zoom"), visual.get("pageX"), visual.get("pageY")
        vw, vh, lw, lh = (
            visual.get("clientWidth"),
            visual.get("clientHeight"),
            layout.get("clientWidth"),
            layout.get("clientHeight"),
        )
        if all(isinstance(v, (int, float)) for v in (zoom, x, y, vw, vh, lw, lh)):
            assert isinstance(zoom, (int, float)) and isinstance(x, (int, float))
            assert isinstance(y, (int, float)) and isinstance(vw, (int, float))
            assert isinstance(vh, (int, float)) and isinstance(lw, (int, float))
            assert isinstance(lh, (int, float))
            evidence["content_css"] = {"width": min(vw, lw), "height": min(vh, lh)}
    evidence["screenshot_parameters"] = {
        "format": "png",
        "fromSurface": True,
        "captureBeyondViewport": False,
    }
    print("Capture geometry: " + json.dumps(evidence, ensure_ascii=False))
    return evidence


async def run_capture_checks(endpoint: str, output: Path, samples: int = 3) -> JsonObject:
    if samples < 1:
        raise ValueError("samples must be positive")
    output.mkdir(parents=True, exist_ok=True)
    session = BrowserSession(endpoint)
    provider = BrowserCaptureProvider(session)
    registry = ProviderRegistry()
    registry.register(provider)
    created: list[str] = []
    records: list[JsonValue] = []
    geometry_records: list[JsonValue] = []
    report: JsonObject = {
        "captures": records,
        "geometry": geometry_records,
        "status": "running",
        "unit": "ms",
        "timing_scope": (
            "await capture including geometry, CDP, PNG validation/crop; excludes disk I/O"
        ),
        "unverified": ["WebGL", "manual browser Ctrl+/- zoom", "pinch zoom (unsupported)"],
    }
    try:
        await session.connect()
        report["browser_version"] = await session.connection.send("Browser.getVersion")
        for url in ("data:text/html," + quote(HTML), "about:blank"):
            result = await session.connection.send("Target.createTarget", {"url": url})
            target = result.get("targetId")
            assert isinstance(target, str)
            created.append(target)
        await session.bind(created[0])
        # The second disposable target made the fixture hidden. Establish a visible
        # baseline; background capture is tested separately and explicitly below.
        await session.send("Page.bringToFront")
        async with asyncio.timeout(10):
            while await evaluate(session, "typeof window.paint === 'function'") is not True:
                await asyncio.sleep(0.05)
        await provider.start()
        identity = (session.page_id, session.session_id, session.generation)
        for width, height, dpr in ((640, 480, 1), (720, 540, 1.5), (800, 600, 2)):
            await session.send(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": dpr,
                    "mobile": False,
                },
            )
            await evaluate(session, "scrollTo(80,120); paint('rgb(0,0,255)'); true")
            # Require the measured scroll to settle, without depending on background rAF.
            async with asyncio.timeout(10):
                while await evaluate(session, "scrollX === 80 && scrollY === 120") is not True:
                    await asyncio.sleep(0.05)
            evidence = await geometry_evidence(session)
            geometry_records.append(evidence)
            dom = evidence["dom"]
            assert isinstance(dom, dict)
            dom_width, dom_height = dom.get("width"), dom.get("height")
            assert isinstance(dom_width, (int, float)) and isinstance(dom_height, (int, float))
            full_times: list[float] = []
            region_times: list[float] = []
            for index in range(samples):
                start = perf_counter()
                full = await registry.get(BrowserCaptureProvider).capture(created[0])
                full_times.append((perf_counter() - start) * 1000)
                # Save first, so a size/color assertion failure leaves visual evidence.
                (output / f"{width}x{height}-dpr{dpr}-{index}-full.png").write_bytes(full.data)
                assert abs(full.viewport.width - dom_width) <= 1, evidence
                assert abs(full.viewport.height - dom_height) <= 1, evidence
                assert abs(full.width - dom_width * dpr) <= 2, (full.width, evidence)
                assert abs(full.height - dom_height * dpr) <= 2, (full.height, evidence)
                assert_color(full, dom_width - 20, dom_height - 20, (255, 0, 255))
                assert_color(full, 60, 60, (255, 0, 0))
                assert_color(full, 170, 60, (0, 0, 255))
                assert full.viewport.scroll_y == 120
                assert full.viewport.scroll_x == 80
                assert math.isclose(full.viewport.device_scale_factor, dpr, rel_tol=1e-6), (
                    full.viewport.device_scale_factor,
                    dpr,
                )
                start = perf_counter()
                region = await provider.capture_region(
                    created[0], x=40.25, y=40.25, width=79.25, height=79.25
                )
                region_times.append((perf_counter() - start) * 1000)
                assert_color(region, 60, 60, (255, 0, 0))
                assert region.pixel_to_css(0, 0) == (
                    region.viewport.capture_x,
                    region.viewport.capture_y,
                )
                assert region.viewport.capture_x <= 40.25
                assert region.viewport.capture_y <= 40.25
                assert region.viewport.capture_x + region.viewport.capture_width >= 119.5 - 1e-6
                edge = await provider.capture_region(
                    created[0],
                    x=full.viewport.width - 35.25,
                    y=full.viewport.height - 35.25,
                    width=35.25,
                    height=35.25,
                )
                (output / f"{width}x{height}-dpr{dpr}-{index}-edge.png").write_bytes(edge.data)
                assert_color(edge, dom_width - 20, dom_height - 20, (255, 0, 255))
                assert (
                    abs(
                        edge.viewport.capture_x
                        + edge.viewport.capture_width
                        - full.viewport.capture_width
                    )
                    < 1e-6
                )
                assert (
                    abs(
                        edge.viewport.capture_y
                        + edge.viewport.capture_height
                        - full.viewport.capture_height
                    )
                    < 1e-6
                )
                assert edge.pixel_to_css(0, 0) == (edge.viewport.capture_x, edge.viewport.capture_y)
                for name, frame in (("full", full), ("region", region), ("edge", edge)):
                    filename = f"{width}x{height}-dpr{dpr}-{index}-{name}.png"
                    (output / filename).write_bytes(frame.data)
                    records.append({"file": filename, "frame": to_dict(frame)})
                assert (session.page_id, session.session_id, session.generation) == identity
            report[f"timing_{width}x{height}_dpr{dpr}"] = {
                "samples": samples,
                "full_ms": [value for value in full_times],
                "region_ms": [value for value in region_times],
                "full_median_ms": median(full_times),
                "region_median_ms": median(region_times),
            }
        await evaluate(
            session,
            "paint('rgb(0,128,0)'); "
            "new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))",
        )
        foreground_canvas = await provider.capture(created[0])
        (output / "foreground-canvas.png").write_bytes(foreground_canvas.data)
        assert_color(foreground_canvas, 170, 60, (0, 128, 0))
        report["canvas_changed_color"] = True
        # Verify navigation while visible, before probing a potentially stalled
        # hidden surface. A timed-out screenshot is not safe to blindly retry.
        await session.send("Emulation.clearDeviceMetricsOverride")
        destination = "data:text/html," + quote(HTML + "<!-- navigation -->")
        navigation = await session.send("Page.navigate", {"url": destination})
        assert "errorText" not in navigation, navigation
        async with asyncio.timeout(10):
            while await evaluate(session, "typeof window.paint === 'function'") is not True:
                await asyncio.sleep(0.05)
        await evaluate(
            session, "new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))"
        )
        after_navigation = await provider.capture(created[0])
        assert after_navigation.session_id == identity[1]
        assert_color(after_navigation, 170, 60, (0, 0, 255))
        report["navigation_capture"] = to_dict(after_navigation)
        await session.connection.send("Target.activateTarget", {"targetId": created[1]})
        report["visibility_before_background_capture"] = await evaluate(
            session, "document.visibilityState"
        )
        await evaluate(session, "paint('rgb(0,128,0)'); true")
        try:
            background = await provider.capture(created[0])
        except CDPTimeoutError:
            report["background_capture"] = "timed_out_without_surface_frame"
            assert session.connection.pending_count == 0
        else:
            assert_color(background, 170, 60, (0, 128, 0))
            (output / "background-canvas.png").write_bytes(background.data)
            report["background_capture"] = "passed"
        report["visibility_after_background_capture"] = await evaluate(
            session, "document.visibilityState"
        )
        await session.connection.send("Target.closeTarget", {"targetId": created[0]})
        async with asyncio.timeout(10):
            while session.is_ready:
                await asyncio.sleep(0.01)
        try:
            await provider.capture(created[0])
        except CapabilityUnavailableError:
            report["closed_target_rejected"] = True
        else:
            raise AssertionError("closed target capture was accepted")
        report["status"] = "passed"
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        await provider.close()
        try:
            for target in created:
                if session.connected:
                    with suppress(BrowserError):
                        await session.connection.send("Target.closeTarget", {"targetId": target})
        finally:
            await session.close()
            report["cleanup"] = {
                "pending_count": session.connection.pending_count,
                "reader_running": session.connection.reader_running,
                "connected": session.connected,
            }
            (output / "capture-report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    assert session.connection.pending_count == 0
    assert not session.connection.reader_running and not session.connected
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.environ.get("BCA_CDP_ENDPOINT"))
    parser.add_argument("--output", type=Path, default=Path("capture-artifacts"))
    parser.add_argument("--samples", type=int, default=3)
    args = parser.parse_args()
    if not args.endpoint:
        parser.error("provide --endpoint or BCA_CDP_ENDPOINT; browser startup is manual")
    report = asyncio.run(run_capture_checks(args.endpoint, args.output, args.samples))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
