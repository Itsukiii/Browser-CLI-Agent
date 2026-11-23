"""G1/G2: explicit isolated Edge, OS desktop shortcuts and real reply-loss relay."""
# ruff: noqa: E402 -- optional native dependencies

import asyncio
import ctypes
import json
import math
import os
import threading
import time
from pathlib import Path
from urllib.parse import quote

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("maa")
from PIL import Image
from websockets.asyncio.client import connect

from bca.core.browser import BrowserCaptureProvider, BrowserInputProvider, BrowserSession
from bca.core.protocol import to_dict
from bca.lite.bridge import CDPBridge, run_native
from examples.browser_end_to_end import HTML, evaluate
from tests.core.runtime.cdp_fault_proxy import ReplyLossProxy
from tests.lite.test_real_bridge import Capture, TracedController

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(
        not os.environ.get("BCA_CDP_ENDPOINT"), reason="explicit isolated Edge required"
    ),
]
TITLE = "BCAZoomFixture_92741"
PAGE = HTML.replace("BCA End to End", TITLE).replace(
    "window.hits=[];",
    "window.events=[];['mousedown','mouseup'].forEach(k=>document.addEventListener(k,e=>events.push({type:k,x:e.clientX,y:e.clientY,target:e.target.id})));window.hits=[];",
)


def output_dir(tmp_path):
    path = Path(os.environ.get("BCA_LITE_ADDENDUM_OUTPUT", str(tmp_path)))
    path.mkdir(parents=True, exist_ok=True)
    return path


async def create_page(session, *, window=False):
    target = (
        await session.connection.send(
            "Target.createTarget",
            {"url": "data:text/html;charset=utf-8," + quote(PAGE), "newWindow": window},
        )
    )["targetId"]
    await session.bind(target)
    await session.send("Page.bringToFront")
    async with asyncio.timeout(10):
        while not await evaluate(session, "typeof hits==='object'"):
            await asyncio.sleep(0.02)
    return target


def desktop_key(key):
    """Only send OS keys after checking exact owned fixture window title."""
    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = ctypes.c_void_p
    title = ctypes.create_unicode_buffer(512)
    handles = []
    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @callback
    def visit(hwnd, unused):
        caption = ctypes.create_unicode_buffer(512)
        cls = ctypes.create_unicode_buffer(128)
        u.GetWindowTextW(ctypes.c_void_p(hwnd), caption, 512)
        u.GetClassNameW(ctypes.c_void_p(hwnd), cls, 128)
        if caption.value.startswith(TITLE) and cls.value == "Chrome_WidgetWin_1":
            handles.append(hwnd)
        return True

    u.EnumWindows(visit, 0)
    assert len(handles) == 1, "Expected one owned Chromium fixture window"
    hwnd = ctypes.c_void_p(handles[0])
    u.ShowWindow(hwnd, 9)  # Restore only the owned fixture window.
    foreground = ctypes.c_void_p(u.GetForegroundWindow())
    tid = u.GetWindowThreadProcessId(foreground, None)
    current = ctypes.windll.kernel32.GetCurrentThreadId()
    attached = bool(u.AttachThreadInput(current, tid, True)) if current != tid else False
    try:
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
    finally:
        if attached:
            u.AttachThreadInput(current, tid, False)
    time.sleep(0.2)
    hwnd = u.GetForegroundWindow()
    u.GetWindowTextW(ctypes.c_void_p(hwnd), title, 512)
    if hwnd != handles[0]:
        raise RuntimeError("Owned Edge fixture is not foreground; no keys sent")
    u.keybd_event(0x11, 0, 0, 0)
    try:
        u.keybd_event(key, 0, 0, 0)
        u.keybd_event(key, 0, 2, 0)
    finally:
        u.keybd_event(0x11, 0, 2, 0)
    return {"shortcut": f"Ctrl+VK_{key:02X}", "foreground_owned": True}


async def metrics(session):
    return {
        "runtime": await evaluate(
            session,
            "({dpr:devicePixelRatio,width:innerWidth,height:innerHeight,scale:visualViewport.scale,x:scrollX,y:scrollY})",
        ),
        "layout": await session.send("Page.getLayoutMetrics"),
    }


async def finish(session, capture, inputs, target, original, report):
    await inputs.close()
    await capture.close()
    if target:
        await session.connection.send("Target.closeTarget", {"targetId": target})
    remaining = await remaining_after_close(session, target)
    report["owned_targets_remaining"] = sorted(remaining & {target})
    report["preexisting_targets_preserved"] = original.issubset(remaining)
    await session.close()
    report["cleanup"] = {
        "pending": session.connection.pending_count,
        "reader": session.connection.reader_running,
        "connected": session.connected,
    }
    assert report["cleanup"] == {"pending": 0, "reader": False, "connected": False}
    assert not report["owned_targets_remaining"] and report["preexisting_targets_preserved"]


async def remaining_after_close(session, target):
    async with asyncio.timeout(5):
        while True:
            remaining = {t.target_id for t in await session.list_targets()}
            if target not in remaining:
                return remaining
            await asyncio.sleep(0.02)


def test_desktop_zoom_authorized_native_clicks(tmp_path):
    output = output_dir(tmp_path)

    async def scenario():
        session = BrowserSession(os.environ["BCA_CDP_ENDPOINT"])
        capture, inputs = Capture(session), BrowserInputProvider(session)
        report = {
            "status": "running",
            "mechanism": "Windows desktop Ctrl+0 / Ctrl+- / Ctrl+=",
            "owner_thread": threading.get_ident(),
            "groups": [],
            "shortcuts": [],
        }
        target = None
        try:
            await session.connect()
            report["browser"] = await session.connection.send("Browser.getVersion")
            original = {t.target_id for t in await session.list_targets()}
            target = await create_page(session, window=True)
            await asyncio.sleep(0.3)
            report["shortcuts"].append(desktop_key(0x30))
            await asyncio.sleep(0.3)
            baseline = await metrics(session)
            report["baseline_100"] = baseline
            await capture.start()
            await inputs.start()
            for percent, keys in [(80, [0xBD, 0xBD]), (100, []), (125, [0xBB, 0xBB])]:
                report["shortcuts"].append(desktop_key(0x30))
                for key in keys:
                    report["shortcuts"].append(desktop_key(key))
                    await asyncio.sleep(0.2)
                await asyncio.sleep(0.3)
                measured = await metrics(session)
                ratio = measured["runtime"]["dpr"] / baseline["runtime"]["dpr"]
                assert abs(ratio - percent / 100) < 0.001
                assert measured["runtime"]["scale"] == 1
                await evaluate(session, "scrollTo(80,120)")
                report["before_capture"] = await metrics(session)
                from bca.core.browser.geometry import measure_geometry

                try:
                    await measure_geometry(session)
                except Exception as exc:
                    report["geometry_error"] = str(exc)
                    raise
                for raw in (True, False):
                    bridge = CDPBridge(
                        loop=asyncio.get_running_loop(),
                        session=session,
                        capture=capture,
                        input_provider=inputs,
                        require_authorization=True,
                    )
                    ctrl = await asyncio.to_thread(TracedController, bridge, raw_size=raw)
                    record = {"percent": percent, "ratio": ratio, "metrics": measured, "raw": raw}
                    try:
                        assert await run_native(
                            bridge, lambda ctrl=ctrl: ctrl.post_connection().wait().succeeded
                        )
                        if not raw:
                            assert await asyncio.to_thread(
                                ctrl.set_screenshot_target_short_side, 360
                            )

                        def screenshot(ctrl=ctrl, bridge=bridge):
                            job = ctrl.post_screencap().wait()
                            assert job.succeeded, bridge.last_error
                            return job.get()

                        image = await run_native(bridge, screenshot)
                        ref = bridge.observation
                        assert ref is not None
                        ys, xs = np.where(
                            (image[:, :, 2] > 240) & (image[:, :, 1] < 15) & (image[:, :, 0] < 15)
                        )
                        point = (
                            round(float(xs.min() + xs.max()) / 2),
                            round(float(ys.min() + ys.max()) / 2),
                        )
                        await bridge.authorize(ref)
                        assert await run_native(
                            bridge,
                            lambda ctrl=ctrl, point=point: ctrl.post_click(*point).wait().succeeded,
                        )
                        assert not await run_native(
                            bridge,
                            lambda ctrl=ctrl, point=point: ctrl.post_click(*point).wait().succeeded,
                        )
                        callback = [c for c in ctrl.calls if c["callback"] == "click"][0]
                        raw_point = [
                            math.floor(
                                point[i]
                                * (ref.frame.width, ref.frame.height)[i]
                                / (image.shape[1], image.shape[0])[i]
                                + 0.5
                            )
                            for i in range(2)
                        ]
                        assert [callback["x"], callback["y"]] == raw_point
                        css = ref.frame.pixel_to_css(*raw_point)
                        hits = await evaluate(session, "hits.splice(0)")
                        assert len(hits) == 1 and hits[0]["target"] == "mark"
                        assert all(abs(hits[0][a] - css[i]) <= 1 for i, a in enumerate(("x", "y")))
                        Image.fromarray(image[:, :, ::-1]).save(
                            output / f"zoom-{percent}-raw-{raw}.png"
                        )
                        # New observation invalidated during a real desktop zoom change.
                        await run_native(bridge, screenshot)
                        await bridge.authorize(bridge.observation)
                        report["shortcuts"].append(desktop_key(0xBB))
                        await asyncio.sleep(0.2)
                        assert not await run_native(
                            bridge,
                            lambda ctrl=ctrl, point=point: ctrl.post_click(*point).wait().succeeded,
                        )
                        assert await evaluate(session, "hits.length") == 0
                        record["stale_zoom_rejected"] = bridge.last_error
                        report["shortcuts"].append(desktop_key(0xBD))
                        await asyncio.sleep(0.2)
                        record.update(
                            frame=to_dict(ref.frame),
                            maa_size=[image.shape[1], image.shape[0]],
                            point=point,
                            native_callback=callback,
                            css=css,
                            dom=hits[0],
                            calls=ctrl.calls,
                        )
                        assert all(c["thread"] != report["owner_thread"] for c in ctrl.calls)
                        report["groups"].append(record)
                    finally:
                        await asyncio.to_thread(ctrl.close)
                        await bridge.aclose()
            report["status"] = "passed"
        finally:
            if target and session.is_ready:
                try:
                    report["shortcuts"].append(desktop_key(0x30))
                    await asyncio.sleep(0.2)
                except RuntimeError:
                    report["reset_skipped"] = "fixture lost foreground; owned target closed below"
            await finish(session, capture, inputs, target, original, report)
            (output / "zoom.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    asyncio.run(scenario())


class EvidenceProxy(ReplyLossProxy):
    """Record the actual upstream response before dropping/holding it."""

    def __init__(self, endpoint, mode):
        super().__init__(endpoint)
        self.mode = mode
        self.trace = []
        self.release = asyncio.Event()
        self.arm = False

    async def handle(self, client):
        async with connect(self.upstream, proxy=None, max_size=16 * 1024 * 1024) as upstream:
            self.sockets.update((client, upstream))
            pending = {}

            async def forward():
                async for wire in client:
                    request = json.loads(wire)
                    pending[request["id"]] = request
                    await upstream.send(wire)
                    self.requests.append(request)
                    self.trace.append(
                        {
                            "event": "forwarded",
                            "id": request["id"],
                            "method": request["method"],
                            "params": request.get("params", {}),
                            "time": time.monotonic(),
                        }
                    )

            async def replies():
                async for wire in upstream:
                    reply = json.loads(wire)
                    req = pending.pop(reply.get("id"), {})
                    matches = self.arm and (
                        req.get("method") == "Page.captureScreenshot"
                        if self.mode == "close"
                        else req.get("params", {}).get("type") == "mousePressed"
                    )
                    if matches:
                        self.arm = False
                        self.trace.append(
                            {
                                "event": "edge_reply_intercepted",
                                "request": req,
                                "reply_id": reply.get("id"),
                                "success": "result" in reply,
                                "mode": self.mode,
                                "time": time.monotonic(),
                            }
                        )
                        self.dropped.append(req)
                        self.seen.set()
                        if self.mode == "disconnect":
                            self.trace.append({"event": "disconnect_after_edge_reply"})
                            await client.close()
                            return
                        if self.mode == "close":
                            await self.release.wait()
                            self.trace.append({"event": "held_reply_released", "id": reply["id"]})
                            await client.send(wire)
                        else:
                            self.trace.append({"event": "ack_discarded", "id": reply["id"]})
                        continue
                    await client.send(wire)

            tasks = [asyncio.create_task(forward()), asyncio.create_task(replies())]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                self.sockets.difference_update((client, upstream))


@pytest.mark.parametrize("mode", ["drop", "disconnect", "close"])
def test_real_transport_faults(tmp_path, mode):
    output = output_dir(tmp_path)

    async def scenario():
        endpoint = os.environ["BCA_CDP_ENDPOINT"]
        oracle = BrowserSession(endpoint)
        await oracle.connect()
        original = {t.target_id for t in await oracle.list_targets()}
        target = await create_page(oracle)
        report = {"status": "running", "mode": mode, "owner_thread": threading.get_ident()}
        async with EvidenceProxy(endpoint, mode) as proxy:
            session = BrowserSession(proxy.url)
            capture = BrowserCaptureProvider(session)
            inputs = BrowserInputProvider(session, timeout=0.3)
            bridge = ctrl = None
            try:
                await session.connect()
                await session.bind(target)
                await capture.start()
                await inputs.start()
                bridge = CDPBridge(
                    loop=asyncio.get_running_loop(),
                    session=session,
                    capture=capture,
                    input_provider=inputs,
                    timeout=3,
                    require_authorization=True,
                )
                ctrl = await asyncio.to_thread(TracedController, bridge)
                assert await run_native(
                    bridge, lambda ctrl=ctrl: ctrl.post_connection().wait().succeeded
                )
                if mode != "close":
                    assert await run_native(bridge, lambda: ctrl.post_screencap().wait().succeeded)
                    ref = bridge.observation
                    # Point chosen from actual captured red pixels.
                    image = await asyncio.to_thread(lambda: ctrl.cached_image)
                    ys, xs = np.where(
                        (image[:, :, 2] > 240) & (image[:, :, 1] < 15) & (image[:, :, 0] < 15)
                    )
                    point = (
                        round(float(xs.min() + xs.max()) / 2),
                        round(float(ys.min() + ys.max()) / 2),
                    )
                    await bridge.authorize(ref)
                    proxy.arm = True
                    success = await run_native(
                        bridge,
                        lambda ctrl=ctrl, point=point: ctrl.post_click(*point).wait().succeeded,
                    )
                    assert not success and proxy.seen.is_set()
                    assert bridge.input_outcome == "unknown"
                    assert not await run_native(
                        bridge,
                        lambda ctrl=ctrl, point=point: ctrl.post_click(*point).wait().succeeded,
                    )
                    assert not await run_native(
                        bridge, lambda: ctrl.post_screencap().wait().succeeded
                    )
                    events = await evaluate(oracle, "events")
                    assert len([e for e in events if e["type"] == "mousedown"]) == 1
                    report["dom_events"] = events
                    report["input_diagnostic"] = to_dict(inputs.last_error)
                    assert inputs.input_state_uncertain
                else:
                    proxy.arm = True
                    task = asyncio.create_task(
                        run_native(bridge, lambda: ctrl.post_screencap().wait().succeeded)
                    )
                    await asyncio.wait_for(proxy.seen.wait(), 5)
                    task.cancel()
                    await asyncio.sleep(0.03)
                    assert not task.done()
                    closing = asyncio.create_task(bridge.aclose())
                    await asyncio.sleep(0.03)
                    assert not closing.done()
                    report["close_waited_for_callback"] = True
                    proxy.release.set()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                    await closing
                    assert not await run_native(
                        bridge, lambda: ctrl.post_click(10, 10).wait().succeeded
                    )
                    report["dom_events"] = await evaluate(oracle, "events")
                    assert report["dom_events"] == []
                report["outcome"] = bridge.input_outcome
                report["last_error"] = bridge.last_error
                report["calls"] = ctrl.calls
                assert all(c["thread"] != report["owner_thread"] for c in ctrl.calls)
                presses = [
                    r for r in proxy.requests if r.get("params", {}).get("type") == "mousePressed"
                ]
                assert len(presses) == (0 if mode == "close" else 1)
                assert len(proxy.dropped) == 1
                report["forwarded_mouse_pressed"] = len(presses)
                report["status"] = "passed"
            finally:
                proxy.release.set()
                if ctrl:
                    await asyncio.to_thread(ctrl.close)
                    report["native_handle_released"] = ctrl._handle is None
                if bridge:
                    await bridge.aclose()
                await inputs.close()
                await capture.close()
                await session.close()
                report["cleanup"] = {
                    "pending": session.connection.pending_count,
                    "reader": session.connection.reader_running,
                    "connected": session.connected,
                }
                # Save only test-owned target command data; no user target metadata.
                report["proxy_trace"] = [
                    r
                    for r in proxy.trace
                    if r.get("method") not in ("Runtime.evaluate", "Target.createTarget")
                ]
        report["proxy_sockets_remaining"] = len(proxy.sockets)
        await oracle.connection.send("Target.closeTarget", {"targetId": target})
        remaining = await remaining_after_close(oracle, target)
        report["owned_targets_remaining"] = sorted(remaining & {target})
        report["preexisting_targets_preserved"] = original.issubset(remaining)
        await oracle.close()
        (output / f"fault-{mode}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        assert report["cleanup"] == {"pending": 0, "reader": False, "connected": False}
        assert report["proxy_sockets_remaining"] == 0 and report["native_handle_released"]
        assert not report["owned_targets_remaining"] and report["preexisting_targets_preserved"]

    asyncio.run(scenario())
