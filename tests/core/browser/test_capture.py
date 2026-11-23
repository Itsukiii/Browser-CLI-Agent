import asyncio
import base64
import json
import math
from io import BytesIO

import pytest
from PIL import Image

from bca.core.browser import (
    BrowserCaptureProvider,
    BrowserSession,
    CaptureError,
    CDPCommandError,
    CDPDisconnectedError,
    CDPTimeoutError,
    TargetLostError,
)
from bca.core.errors import CapabilityUnavailableError, LifecycleError, ValidationError
from bca.core.providers import CaptureProvider, ProviderRegistry

from .mock_cdp import MockCDP


def png(width=200, height=100, format="PNG"):
    output = BytesIO()
    with Image.new("RGB", (width, height), (10, 20, 30)) as image:
        image.save(output, format=format)
    return output.getvalue()


class CapturePeer(MockCDP):
    def __init__(self):
        super().__init__()
        self.visual = dict(
            clientWidth=100,
            clientHeight=50,
            pageX=30,
            pageY=80,
            offsetX=0,
            offsetY=0,
            scale=1,
            zoom=1,
        )
        self.runtime = dict(dpr=2, x=30, y=80, href="about:blank", timeOrigin=1000)
        self.layout = None  # Independent layout geometry in compatibility regressions.
        self.screenshot = {"data": base64.b64encode(png()).decode()}
        self.gate = asyncio.Event()
        self.gate.set()
        self.after_capture = None
        self.metrics_missing = False

    async def _reply(self, socket, request):
        method = request["method"]
        if method in self.fail_methods:
            return await super()._reply(socket, request)
        if method == "Page.getLayoutMetrics":
            result = (
                {}
                if self.metrics_missing
                else {
                    "cssVisualViewport": self.visual,
                    "cssLayoutViewport": self.layout if self.layout is not None else self.visual,
                }
            )
        elif method == "Runtime.evaluate":
            result = {
                "result": {
                    "type": "object",
                    "value": {
                        "surfaceWidth": self.visual["clientWidth"],
                        "surfaceHeight": self.visual["clientHeight"],
                        **self.runtime,
                    },
                }
            }
        elif method == "Page.captureScreenshot":
            await self.gate.wait()
            result = self.screenshot
            if self.after_capture:
                self.after_capture()
        else:
            return await super()._reply(socket, request)
        response = {"id": request["id"], "sessionId": request["sessionId"], "result": result}
        try:
            await socket.send(json.dumps(response))
        except Exception:
            pass


async def ready(peer, **kwargs):
    session = BrowserSession(peer.endpoint)
    await session.connect()
    await session.bind("page-a")
    provider = BrowserCaptureProvider(session, **kwargs)
    await provider.start()
    return session, provider


@pytest.mark.parametrize(
    "dpr,zoom,pixels",
    [(1, 1, (100, 50)), (2, 1, (200, 100)), (1.5, 1.25, (151, 77)), (2, 1, (203, 71))],
)
def test_full_frame_and_fractional_region_use_actual_pixels(dpr, zoom, pixels):
    async def scenario():
        async with CapturePeer() as peer:
            peer.runtime["dpr"] = dpr
            peer.visual["zoom"] = zoom
            peer.screenshot["data"] = base64.b64encode(png(*pixels)).decode()
            session, provider = await ready(peer)
            identity = session.page_id, session.session_id, session.generation
            full = await provider.capture("page-a")
            assert (full.width, full.height) == pixels
            assert full.page_id == "page-a" and full.session_id == session.session_id
            assert full.captured_at.utcoffset().total_seconds() == 0
            assert full.viewport.device_scale_factor == dpr
            assert full.viewport.scroll_x == 30 and full.viewport.scroll_y == 80
            assert full.pixel_to_css(full.width / 2, full.height / 2) == (50, 25)
            region = await provider.capture_region("page-a", x=10.3, y=5.7, width=20.4, height=10.2)
            v = region.viewport
            assert v.capture_x <= 10.3 and v.capture_y <= 5.7
            assert v.capture_x + v.capture_width >= 30.7 - 1e-10
            assert v.capture_y + v.capture_height >= 15.9 - 1e-10
            assert 10.3 - v.capture_x < 100 / pixels[0]
            assert 5.7 - v.capture_y < 50 / pixels[1]
            assert region.pixel_to_css(0, 0) == (v.capture_x, v.capture_y)
            assert region.pixel_to_css(region.width / 2, region.height / 2) == (
                v.capture_x + v.capture_width / 2,
                v.capture_y + v.capture_height / 2,
            )
            with Image.open(BytesIO(region.data)) as decoded:
                decoded.load()
                assert decoded.size == (region.width, region.height)
            assert full.frame_id != region.frame_id
            assert (session.page_id, session.session_id, session.generation) == identity
            request = next(r for r in peer.requests if r["method"] == "Page.captureScreenshot")
            assert "clip" not in request["params"]
            assert request["params"]["captureBeyondViewport"] is False
            await provider.close()
            assert session.is_ready
            await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"data": None},
        {"data": "???"},
        {"data": base64.b64encode(b"not png").decode()},
        {"data": base64.b64encode(png(format="JPEG")).decode()},
        {"data": base64.b64encode(png()[:-15]).decode()},
        {"data": base64.b64encode(png()[:16] + b"\x00\x00\x00\x01" + png()[20:]).decode()},
    ],
)
def test_malformed_image_or_dimensions_fail(response):
    async def scenario():
        async with CapturePeer() as peer:
            peer.screenshot = response
            session, provider = await ready(peer)
            with pytest.raises(CaptureError):
                await provider.capture("page-a")
            assert session.connection.pending_count == 0
            await provider.close()
            await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["resize", "scroll", "dpr", "zoom", "navigate"])
def test_geometry_or_document_changes_discard_capture(change):
    async def scenario():
        async with CapturePeer() as peer:

            def mutate():
                if change == "resize":
                    peer.visual["clientWidth"] = 101
                elif change == "scroll":
                    peer.visual["pageY"] = 81
                    peer.runtime["y"] = 81
                elif change == "dpr":
                    peer.runtime["dpr"] = 1.5
                elif change == "zoom":
                    peer.visual["zoom"] = 1.25
                else:
                    peer.runtime["timeOrigin"] += 1

            peer.after_capture = mutate
            session, provider = await ready(peer)
            with pytest.raises(CaptureError, match="changed"):
                await provider.capture("page-a")
            await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "operation",
    [
        "unbind",
        "switch",
        "rebind",
        "destroy",
        "disconnect",
        "session_close",
        "provider_close",
        "cancel",
        "timeout",
    ],
)
def test_capture_interruption_and_cleanup(operation):
    async def scenario():
        async with CapturePeer() as peer:
            session, provider = await ready(peer, timeout=0.2 if operation == "timeout" else 2)
            peer.gate.clear()
            task = asyncio.create_task(provider.capture("page-a"))
            await peer.seen("Page.captureScreenshot")
            error = TargetLostError
            if operation == "unbind":
                await session.unbind()
            elif operation == "switch":
                await session.bind("page-b")
            elif operation == "rebind":
                await session.unbind()
                await session.bind("page-a")
            elif operation == "destroy":
                await peer.emit("Target.targetDestroyed", {"targetId": "page-a"})
            elif operation == "disconnect":
                with pytest.raises(CDPDisconnectedError):
                    await session.send("Test.disconnect")
                error = CDPDisconnectedError
            elif operation == "session_close":
                await session.close()
                error = CDPDisconnectedError
            elif operation == "provider_close":
                await provider.close()
            elif operation == "cancel":
                task.cancel()
                error = asyncio.CancelledError
            elif operation == "timeout":
                error = CDPTimeoutError
            if operation != "timeout":
                peer.gate.set()
            with pytest.raises(error):
                await task
            peer.gate.set()
            assert session.connection.pending_count == 0
            await provider.close()
            await session.close()
            assert not session.connection.reader_running

    asyncio.run(scenario())


def test_lifecycle_registry_and_invalid_requests():
    async def scenario():
        async with CapturePeer() as peer:
            session = BrowserSession(peer.endpoint)
            provider = BrowserCaptureProvider(session)
            registry = ProviderRegistry()
            registry.register(provider)
            assert not registry.available(CaptureProvider)
            with pytest.raises(CapabilityUnavailableError):
                await provider.start()
            await session.connect()
            await session.bind("page-a")
            await provider.start()
            await provider.start()
            assert registry.get(CaptureProvider) is provider
            for page in ("", "wrong", "has space"):
                with pytest.raises(ValidationError):
                    await provider.capture(page)
            for region in ((-1, 0, 1, 1), (0, 0, 0, 1), (99, 0, 2, 1), (0, 0, float("nan"), 1)):
                x, y, w, h = region
                with pytest.raises(ValidationError):
                    await provider.capture_region("page-a", x=x, y=y, width=w, height=h)
            peer.fail_methods.add("Page.captureScreenshot")
            with pytest.raises(CDPCommandError):
                await provider.capture("page-a")
            await provider.close()
            await provider.close()
            assert session.is_ready and not registry.available(CaptureProvider)
            with pytest.raises(CapabilityUnavailableError):
                await provider.capture("page-a")
            with pytest.raises(LifecycleError):
                await provider.start()
            await session.close()

    asyncio.run(scenario())


def test_concurrent_captures_serialize_and_cancelled_waiter_does_not_leak():
    async def scenario():
        async with CapturePeer() as peer:
            session, provider = await ready(peer)
            peer.gate.clear()
            first = asyncio.create_task(provider.capture("page-a"))
            await peer.seen("Page.captureScreenshot")
            second = asyncio.create_task(provider.capture("page-a"))
            await asyncio.sleep(0)
            assert sum(r["method"] == "Page.captureScreenshot" for r in peer.requests) == 1
            second.cancel()
            with pytest.raises(asyncio.CancelledError):
                await second
            peer.gate.set()
            a = await first
            b = await provider.capture("page-a")
            assert a.frame_id != b.frame_id
            assert session.connection.pending_count == 0
            await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", ["missing", "pinch", "offset", "zero", "bool", "runtime"])
def test_invalid_geometry_is_not_returned(invalid):
    async def scenario():
        async with CapturePeer() as peer:
            if invalid == "missing":
                peer.metrics_missing = True
            elif invalid == "pinch":
                peer.visual["scale"] = 2
            elif invalid == "offset":
                peer.visual["offsetX"] = 3
            elif invalid == "zero":
                peer.visual["clientWidth"] = 0
            elif invalid == "bool":
                peer.runtime["dpr"] = True
            else:
                peer.runtime = {}
            session, provider = await ready(peer)
            with pytest.raises(CaptureError):
                await provider.capture("page-a")
            await session.close()

    asyncio.run(scenario())


def test_region_contains_exact_outward_rounded_source_pixels_and_resize_between_calls():
    async def scenario():
        async with CapturePeer() as peer:
            with Image.new("RGB", (203, 71)) as source:
                source.putdata(
                    [(x % 256, y % 256, (x + y) % 256) for y in range(71) for x in range(203)]
                )
                output = BytesIO()
                source.save(output, format="PNG")
                peer.screenshot["data"] = base64.b64encode(output.getvalue()).decode()
                session, provider = await ready(peer)
                frame = await provider.capture_region(
                    "page-a", x=10.3, y=5.7, width=20.4, height=10.2
                )
                bounds = (
                    math.floor(10.3 * 203 / 100),
                    math.floor(5.7 * 71 / 50),
                    math.ceil(30.7 * 203 / 100),
                    math.ceil(15.9 * 71 / 50),
                )
                with source.crop(bounds) as expected, Image.open(BytesIO(frame.data)) as actual:
                    assert actual.size == expected.size
                    assert actual.tobytes() == expected.tobytes()
                peer.visual.update(clientWidth=80, clientHeight=40, zoom=1.25)
                peer.runtime["dpr"] = 2.5
                peer.screenshot["data"] = base64.b64encode(png(200, 100)).decode()
                resized = await provider.capture("page-a")
                assert resized.viewport.width == 80 and resized.viewport.height == 40
                assert resized.pixel_to_css(100, 50) == (40, 20)
                await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("layout_size", [(115, 65), (85, 35), (115, 35), (99.5, 49.5)])
@pytest.mark.parametrize("dpr,zoom", [(1, 1), (1.5, 1.25), (2, 0.8)])
def test_unequal_viewports_capture_content_intersection_and_edge_pixels(layout_size, dpr, zoom):
    async def scenario():
        async with CapturePeer() as peer:
            peer.layout = dict(
                clientWidth=layout_size[0], clientHeight=layout_size[1], pageX=30, pageY=80
            )
            peer.visual.update(pageX=30.25, pageY=80.5, zoom=zoom)
            peer.runtime.update(x=30.25, y=80.5, dpr=dpr)
            w, h = min(100, layout_size[0]), min(50, layout_size[1])
            peer.runtime.update(surfaceWidth=w, surfaceHeight=h)
            pw, ph = round(w * dpr), round(h * dpr)
            with Image.new("RGB", (pw, ph)) as source:
                source.putdata([(x % 256, y % 256, 90) for y in range(ph) for x in range(pw)])
                output = BytesIO()
                source.save(output, format="PNG")
                peer.screenshot["data"] = base64.b64encode(output.getvalue()).decode()
                session, provider = await ready(peer)
                full = await provider.capture("page-a")
                assert (full.viewport.width, full.viewport.height) == (w, h)
                assert full.pixel_to_css(pw - 1, ph - 1) == ((pw - 1) * w / pw, (ph - 1) * h / ph)
                assert (full.viewport.scroll_x, full.viewport.scroll_y) == (30.25, 80.5)
                region = await provider.capture_region(
                    "page-a", x=w - 10.25, y=h - 8.5, width=10.25, height=8.5
                )
                bounds = (math.floor((w - 10.25) * pw / w), math.floor((h - 8.5) * ph / h), pw, ph)
                with source.crop(bounds) as expected, Image.open(BytesIO(region.data)) as actual:
                    assert actual.tobytes() == expected.tobytes()
                    assert actual.size == expected.size
                v = region.viewport
                assert v.capture_x + v.capture_width == pytest.approx(w)
                assert v.capture_y + v.capture_height == pytest.approx(h)
                assert region.pixel_to_css(0, 0) == (bounds[0] * w / pw, bounds[1] * h / ph)
                with pytest.raises(ValidationError):
                    await provider.capture_region("page-a", x=w - 1, y=0, width=1.1, height=1)
                request = next(r for r in peer.requests if r["method"] == "Page.captureScreenshot")
                assert "clip" not in request["params"]
                await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["invalid_width", "origin", "layout_change"])
def test_layout_metrics_are_still_validated_and_rechecked(change):
    async def scenario():
        async with CapturePeer() as peer:
            peer.layout = dict(clientWidth=115, clientHeight=65, pageX=30, pageY=80)
            if change == "invalid_width":
                peer.layout["clientWidth"] = 0
            elif change == "origin":
                peer.layout["pageX"] = 40
            else:
                peer.after_capture = lambda: peer.layout.update(clientWidth=116)
            session, provider = await ready(peer)
            with pytest.raises(CaptureError):
                await provider.capture("page-a")
            assert session.connection.pending_count == 0
            await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("dpr", [1.0000000298023224, 1.5, 2])
def test_native_surface_removes_scrollbars_and_keeps_actual_css_coverage(dpr):
    async def scenario():
        async with CapturePeer() as peer:
            # 100x50 CSS native surface, 85x35 content; remaining pixels are scrollbars.
            peer.visual.update(clientWidth=85, clientHeight=35)
            peer.runtime.update(surfaceWidth=100, surfaceHeight=50, dpr=dpr)
            pw, ph = round(100 * dpr), round(50 * dpr)
            right, bottom = math.floor(85 * pw / 100), math.floor(35 * ph / 50)
            with Image.new("RGB", (pw, ph), "red") as image:
                image.paste((0, 128, 0), (0, 0, right, bottom))
                output = BytesIO()
                image.save(output, format="PNG")
            peer.screenshot["data"] = base64.b64encode(output.getvalue()).decode()
            session, provider = await ready(peer)
            full = await provider.capture("page-a")
            assert (full.width, full.height) == (right, bottom)
            assert full.viewport.device_scale_factor == dpr  # Keep original diagnostic precision.
            assert full.viewport.capture_width == right * 100 / pw
            assert full.viewport.capture_height == bottom * 50 / ph
            assert full.viewport.capture_width <= full.viewport.width
            with Image.open(BytesIO(full.data)) as image:
                assert image.getextrema() == ((0, 0), (128, 128), (0, 0))
            region = await provider.capture_region(
                "page-a", x=74.75, y=24.75, width=10.25, height=10.25
            )
            v = region.viewport
            assert v.capture_x + v.capture_width == pytest.approx(full.viewport.capture_width)
            assert v.capture_y + v.capture_height == pytest.approx(full.viewport.capture_height)
            assert region.pixel_to_css(0, 0) == (
                math.floor(74.75 * pw / 100) * 100 / pw,
                math.floor(24.75 * ph / 50) * 50 / ph,
            )
            await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("delta,accepted", [(7.62939453125e-6, True), (0.001, False)])
def test_desktop_zoom_scroll_measurement_precision(delta, accepted):
    async def scenario():
        async with CapturePeer() as peer:
            peer.runtime["y"] = peer.visual["pageY"] - delta
            session, provider = await ready(peer)
            try:
                if accepted:
                    frame = await provider.capture("page-a")
                    assert frame.viewport.scroll_y == peer.visual["pageY"]
                else:
                    with pytest.raises(CaptureError, match="scroll position changed"):
                        await provider.capture("page-a")
            finally:
                await provider.close()
                await session.close()

    asyncio.run(scenario())
