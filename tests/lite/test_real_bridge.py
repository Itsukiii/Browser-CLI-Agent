"""Opt-in native Maa -> real CDP -> DOM oracle; owns only its created Target."""

# ruff: noqa: E402 -- optional dependency gates precede native imports

import asyncio
import json
import math
import os
import platform
import threading
import time
from pathlib import Path
from urllib.parse import quote

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("maa")
from maa.library import Library
from PIL import Image

from bca.core.browser import BrowserCaptureProvider, BrowserInputProvider, BrowserSession
from bca.core.protocol import to_dict
from bca.lite.bridge import CDPBridge, run_native
from bca.lite.maa_controller import MaaCDPController
from examples.browser_end_to_end import HTML, evaluate

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(
        not os.environ.get("BCA_CDP_ENDPOINT"), reason="explicit isolated CDP required"
    ),
]


class Capture(BrowserCaptureProvider):
    region = False
    frame = None

    async def capture(self, page):
        if self.region:
            self.frame = await self.capture_region(page, x=20, y=20, width=120, height=120)
        else:
            self.frame = await super().capture(page)
        return self.frame


class TracedController(MaaCDPController):
    def __init__(self, bridge, **kwargs):
        self.calls = []
        super().__init__(bridge, **kwargs)

    def screencap(self):
        self.calls.append({"callback": "screencap", "thread": threading.get_ident()})
        return super().screencap()

    def click(self, x, y):
        self.calls.append({"callback": "click", "thread": threading.get_ident(), "x": x, "y": y})
        return super().click(x, y)


def test_real_native_coordinate_matrix_and_stale_guards(tmp_path):
    output = Path(os.environ.get("BCA_LITE_OUTPUT", str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)

    async def scenario():
        session = BrowserSession(os.environ["BCA_CDP_ENDPOINT"])
        capture, inputs = Capture(session), BrowserInputProvider(session)
        target = None
        bridge = None
        report = {
            "status": "running",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "maa": Library.version(),
            "owner_thread": threading.get_ident(),
            "coordinates": [],
            "faults": [],
        }
        try:
            await session.connect()
            original = {t.target_id for t in await session.list_targets()}
            version = await session.connection.send("Browser.getVersion")
            report["browser"] = version["product"]
            target = (
                await session.connection.send(
                    "Target.createTarget", {"url": "data:text/html;charset=utf-8," + quote(HTML)}
                )
            )["targetId"]
            await session.bind(target)
            await session.send("Page.bringToFront")
            async with asyncio.timeout(10):
                while not await evaluate(session, "typeof hits==='object'"):
                    await asyncio.sleep(0.01)
            await capture.start()
            await inputs.start()
            for width, height, dpr in [(960, 540, 1), (720, 540, 1.5), (800, 600, 2)]:
                await session.send(
                    "Emulation.setDeviceMetricsOverride",
                    {"width": width, "height": height, "deviceScaleFactor": dpr, "mobile": False},
                )
                await evaluate(session, "scrollTo(80,120)")
                await evaluate(
                    session, "new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))"
                )
                for region in (False, True):
                    capture.region = region
                    for raw in (False, True):
                        bridge = CDPBridge(
                            loop=asyncio.get_running_loop(),
                            session=session,
                            capture=capture,
                            input_provider=inputs,
                        )

                        def matrix_work(bridge=bridge, raw=raw, dpr=dpr, region=region):
                            ctrl = TracedController(bridge, raw_size=raw)
                            records = []
                            try:
                                assert ctrl.post_connection().wait().succeeded
                                if not raw:
                                    assert ctrl.set_screenshot_target_short_side(360)
                                for sample in range(3):
                                    t0 = time.perf_counter()
                                    job = ctrl.post_screencap().wait()
                                    assert job.succeeded, bridge.last_error
                                    image = job.get()
                                    capture_ms = (time.perf_counter() - t0) * 1000
                                    assert image.flags.c_contiguous and image.dtype == np.uint8
                                    ys, xs = np.where(
                                        (image[:, :, 2] > 240)
                                        & (image[:, :, 1] < 15)
                                        & (image[:, :, 0] < 15)
                                    )
                                    assert len(xs)
                                    point = (
                                        round(float(xs.min() + xs.max()) / 2),
                                        round(float(ys.min() + ys.max()) / 2),
                                    )
                                    if sample == 0:
                                        Image.fromarray(image[:, :, ::-1]).save(
                                            output / f"dpr-{dpr}-region-{region}-raw-{raw}.png"
                                        )
                                    t1 = time.perf_counter()
                                    assert ctrl.post_click(*point).wait().succeeded, (
                                        bridge.last_error
                                    )
                                    click_ms = (time.perf_counter() - t1) * 1000
                                    callback = ctrl.calls[-1]
                                    frame = capture.frame
                                    expected_raw = [
                                        math.floor(point[0] * frame.width / image.shape[1] + 0.5),
                                        math.floor(point[1] * frame.height / image.shape[0] + 0.5),
                                    ]
                                    assert [callback["x"], callback["y"]] == expected_raw
                                    css = frame.pixel_to_css(*expected_raw)
                                    # Pixel-center rounding after Maa resize can move
                                    # the chosen point by one returned image pixel.
                                    assert (
                                        abs(css[0] - 80)
                                        <= 1 + frame.viewport.capture_width / image.shape[1]
                                    )
                                    assert (
                                        abs(css[1] - 80)
                                        <= 1 + frame.viewport.capture_height / image.shape[0]
                                    )
                                    records.append(
                                        {
                                            "dpr": dpr,
                                            "region": region,
                                            "raw": raw,
                                            "sample": sample,
                                            "frame": to_dict(frame),
                                            "maa_size": [image.shape[1], image.shape[0]],
                                            "point": point,
                                            "callback": callback,
                                            "css": css,
                                            "capture_ms": capture_ms,
                                            "click_ms": click_ms,
                                        }
                                    )
                                assert not ctrl.post_click(*point).wait().succeeded  # no replay
                                assert all(
                                    c["thread"] != report["owner_thread"] for c in ctrl.calls
                                )
                            finally:
                                ctrl.close()
                            return records

                        records = await run_native(bridge, matrix_work)
                        hits = await evaluate(session, "hits.splice(0)")
                        assert len(hits) == len(records)
                        for hit, record in zip(hits, records, strict=True):
                            assert hit["target"] == "mark"
                            assert abs(hit["x"] - record["css"][0]) <= 1
                            assert abs(hit["y"] - record["css"][1]) <= 1
                            record["dom"] = hit
                        report["coordinates"].extend(records)
                        await bridge.aclose()
            # Real native jobs must reject observed resize/navigation/disconnection.
            capture.region = False
            for fault in ("resize", "pinch", "navigation", "rebind", "destroy"):
                bridge = CDPBridge(
                    loop=asyncio.get_running_loop(),
                    session=session,
                    capture=capture,
                    input_provider=inputs,
                )
                ready = asyncio.Event()
                proceed = threading.Event()
                loop = asyncio.get_running_loop()

                def fault_work(bridge=bridge, loop=loop, ready=ready, proceed=proceed, fault=fault):
                    ctrl = TracedController(bridge)
                    try:
                        assert ctrl.post_connection().wait().succeeded
                        assert ctrl.post_screencap().wait().succeeded
                        loop.call_soon_threadsafe(ready.set)
                        assert proceed.wait(10)
                        assert not ctrl.post_click(80, 80).wait().succeeded
                        return {
                            "fault": fault,
                            "error": bridge.last_error,
                            "outcome": bridge.input_outcome,
                            "calls": ctrl.calls,
                        }
                    finally:
                        ctrl.close()

                task = asyncio.create_task(run_native(bridge, fault_work))
                try:
                    await asyncio.wait_for(ready.wait(), 10)
                    if fault == "resize":
                        await session.send(
                            "Emulation.setDeviceMetricsOverride",
                            {"width": 900, "height": 600, "deviceScaleFactor": 2, "mobile": False},
                        )
                    elif fault == "pinch":
                        await session.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 2})
                    elif fault == "rebind":
                        await session.unbind()
                        await session.bind(target)
                    elif fault == "navigation":
                        await session.send("Page.navigate", {"url": "about:blank"})
                        async with asyncio.timeout(5):
                            while await evaluate(session, "location.href") != "about:blank":
                                await asyncio.sleep(0.01)
                    else:
                        await session.connection.send("Target.closeTarget", {"targetId": target})
                        async with asyncio.timeout(5):
                            while session.is_ready:
                                await asyncio.sleep(0.01)
                finally:
                    proceed.set()
                report["faults"].append(await task)
                await bridge.aclose()
                if fault == "pinch":
                    await session.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 1})
            report["status"] = "passed"
        finally:
            if bridge:
                await bridge.aclose()
            await inputs.close()
            await capture.close()
            if target and session.connected:
                remaining = {t.target_id for t in await session.list_targets()}
                if target in remaining:
                    await session.connection.send("Target.closeTarget", {"targetId": target})
                remaining = {t.target_id for t in await session.list_targets()}
                report["owned_targets_remaining"] = sorted({target} & remaining)
                report["preexisting_targets_preserved"] = original.issubset(remaining)
            await session.close()
            report["cleanup"] = {
                "pending": session.connection.pending_count,
                "reader": session.connection.reader_running,
                "connected": session.connected,
            }
            (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        assert report["cleanup"] == {"pending": 0, "reader": False, "connected": False}
        assert report["owned_targets_remaining"] == []
        assert report["preexisting_targets_preserved"]

    asyncio.run(scenario())
