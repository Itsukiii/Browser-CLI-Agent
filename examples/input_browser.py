"""Real CDP input acceptance on disposable targets only; report contains fixture data."""

import argparse
import asyncio
import json
import os
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from statistics import median
from time import perf_counter
from urllib.parse import quote

from PIL import Image

from bca.core.browser import (
    BrowserCaptureProvider,
    BrowserError,
    BrowserInputProvider,
    BrowserSession,
)
from bca.core.errors import CapabilityUnavailableError, ValidationError
from bca.core.protocol import (
    Action,
    ActionStatus,
    ActionType,
    JsonObject,
    JsonValue,
    MouseButton,
    to_dict,
)

HTML = """<!doctype html><meta charset=utf-8><title>BCA Input Fixture</title>
<style>html,body{margin:0}body{width:3000px;height:3000px;background:#eee}
#mark{position:fixed;left:40px;top:40px;width:80px;height:80px;background:rgb(255,0,0)}
textarea{position:fixed;left:180px;top:40px;width:250px;height:100px}</style>
<div id=mark></div><textarea id=edit></textarea><script>
window.events=[];
for(const type of ['mousemove','mousedown','mouseup','click','auxclick',
                   'keydown','keyup','input']) {
 document.addEventListener(type,e=>events.push({type:e.type,target:e.target.id,
 x:e.clientX??null,y:e.clientY??null,button:e.button??null,buttons:e.buttons??null,
 key:e.key??null,code:e.code??null,shift:e.shiftKey??false,ctrl:e.ctrlKey??false,
 alt:e.altKey??false,meta:e.metaKey??false,repeat:e.repeat??false}));
}
document.addEventListener('contextmenu',e=>e.preventDefault());
// Disable middle-button browser autoscroll on this controlled event fixture.
document.addEventListener('mousedown',e=>{if(e.button===1)e.preventDefault()});
</script>"""


async def evaluate(session: BrowserSession, expression: str) -> JsonValue:
    result = await session.send(
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        },
    )
    assert "exceptionDetails" not in result, result
    remote = result.get("result")
    assert isinstance(remote, dict)
    return remote.get("value")


async def wait_fixture(session: BrowserSession) -> None:
    async with asyncio.timeout(10):
        while not await evaluate(
            session, "typeof events==='object' && !!document.getElementById('edit')"
        ):
            await asyncio.sleep(0.01)
        await evaluate(
            session, "new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))"
        )


async def run_input_checks(endpoint: str, output: Path) -> JsonObject:
    output.mkdir(parents=True, exist_ok=True)
    report: JsonObject = {
        "status": "running",
        "measurement": "perf_counter around await execute; excludes DOM queries and disk IO",
    }
    results: list[JsonValue] = []
    landings: list[JsonValue] = []
    samples: dict[str, list[float]] = {}
    report["actions"], report["landings"] = results, landings
    session = BrowserSession(endpoint)
    provider = BrowserInputProvider(session)
    capture = BrowserCaptureProvider(session)
    targets: list[str] = []

    async def perform(kind: ActionType, **values: JsonValue) -> None:
        page = session.page_id
        assert page is not None
        # Keep construction fully typed; this fixture never accepts external page content.
        x, y, key, text = values.get("x"), values.get("y"), values.get("key"), values.get("text")
        button = values.get("button")
        action = Action(
            page_id=page,
            type=kind,
            x=float(x) if isinstance(x, (int, float)) else None,
            y=float(y) if isinstance(y, (int, float)) else None,
            key=key if isinstance(key, str) else None,
            text=text if isinstance(text, str) else None,
            button=MouseButton(button) if isinstance(button, str) else None,
        )
        start = perf_counter()
        result = await provider.execute(action)
        elapsed = (perf_counter() - start) * 1000
        samples.setdefault(kind.value, []).append(elapsed)
        results.append({"type": kind.value, "elapsed_ms": elapsed, "result": to_dict(result)})
        assert result.status is ActionStatus.SUCCEEDED, result

    async def key_pair(key: str) -> None:
        await perform(ActionType.KEY_DOWN, key=key)
        await perform(ActionType.KEY_UP, key=key)

    try:
        await session.connect()
        report["browser"] = await session.connection.send("Browser.getVersion")
        for _ in range(2):
            created = await session.connection.send(
                "Target.createTarget", {"url": "data:text/html;charset=utf-8," + quote(HTML)}
            )
            target = created.get("targetId")
            assert isinstance(target, str)
            targets.append(target)
        await session.bind(targets[0])
        await session.send("Page.bringToFront")
        await wait_fixture(session)
        await provider.start()
        await capture.start()
        for width, height, dpr in [(640, 480, 1), (720, 540, 1.5), (800, 600, 2)]:
            await session.send(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": dpr,
                    "mobile": False,
                },
            )
            await evaluate(session, "scrollTo(80,120)")
            await wait_fixture(session)
            geometry = await evaluate(
                session,
                "({w:innerWidth,h:innerHeight,dpr:devicePixelRatio,x:scrollX,y:scrollY,clientWidth:document.documentElement.clientWidth,clientHeight:document.documentElement.clientHeight})",
            )
            assert isinstance(geometry, dict)
            assert geometry["x"] == 80 and geometry["y"] == 120
            assert (
                isinstance(geometry["clientWidth"], (int, float))
                and geometry["clientWidth"] < width
            )
            full = await capture.capture(targets[0])
            region = await capture.capture_region(
                targets[0], x=40.25, y=40.25, width=79.25, height=79.25
            )
            for label, frame in [("full", full), ("region", region)]:
                filename = f"dpr{dpr}-{label}.png"
                (output / filename).write_bytes(frame.data)
                # Locate the red fixture in the PNG, independently of viewport metadata.
                with Image.open(BytesIO(frame.data)) as image:
                    rgb = image.convert("RGB")
                    points = [
                        (x, y)
                        for y in range(rgb.height)
                        for x in range(rgb.width)
                        if rgb.getpixel((x, y)) == (255, 0, 0)
                    ]
                    rgb.close()
                assert points
                px = (min(p[0] for p in points) + max(p[0] for p in points)) / 2
                py = (min(p[1] for p in points) + max(p[1] for p in points)) / 2
                css_x, css_y = frame.pixel_to_css(px, py)
                await evaluate(session, "events.length=0")
                await perform(ActionType.MOUSE_CLICK, x=css_x, y=css_y, button="left")
                observed = await evaluate(session, "events.filter(e=>e.type==='click')")
                assert isinstance(observed, list) and len(observed) == 1
                click = observed[0]
                assert isinstance(click, dict) and click["target"] == "mark"
                assert isinstance(click["x"], (int, float)) and isinstance(click["y"], (int, float))
                dx, dy = click["x"] - css_x, click["y"] - css_y
                assert abs(dx) < 1 and abs(dy) < 1
                landings.append(
                    {
                        "file": filename,
                        "geometry": geometry,
                        "frame": to_dict(frame),
                        "pixel": [px, py],
                        "css": [css_x, css_y],
                        "observed": click,
                        "error_css": [dx, dy],
                    }
                )
            report["resize_bounds_rejected"] = False
            try:
                await provider.execute(
                    Action(page_id=targets[0], type=ActionType.MOUSE_MOVE, x=width, y=height)
                )
            except ValidationError:
                report["resize_bounds_rejected"] = True
            assert report["resize_bounds_rejected"] is True

        await evaluate(session, "events.length=0")
        for button in MouseButton:
            await perform(ActionType.MOUSE_MOVE, x=60.25, y=60.75)
            await perform(ActionType.MOUSE_DOWN, x=60.25, y=60.75, button=button.value)
            await perform(ActionType.MOUSE_MOVE, x=70.25, y=70.75)
            await perform(ActionType.MOUSE_UP, x=70.25, y=70.75, button=button.value)
            await perform(ActionType.MOUSE_CLICK, x=80.25, y=80.75, button=button.value)
        mouse = await evaluate(session, "events")
        assert isinstance(mouse, list)
        report["mouse_events"] = mouse
        for dom_button, mask in [(0, 1), (1, 4), (2, 2)]:
            downs = [
                e
                for e in mouse
                if isinstance(e, dict) and e["type"] == "mousedown" and e["button"] == dom_button
            ]
            ups = [
                e
                for e in mouse
                if isinstance(e, dict) and e["type"] == "mouseup" and e["button"] == dom_button
            ]
            assert len(downs) == len(ups) == 2
            assert all(e["buttons"] == mask for e in downs)
            assert any(
                isinstance(e, dict) and e["type"] == "mousemove" and e["buttons"] == mask
                for e in mouse
            )
        report["mouse_events"] = mouse

        await perform(ActionType.MOUSE_CLICK, x=220, y=70, button="left")
        await evaluate(session, "events.length=0")
        await key_pair("a")
        await perform(ActionType.KEY_DOWN, key="Shift")
        await key_pair("b")
        await perform(ActionType.KEY_UP, key="Shift")
        await key_pair("1")
        await key_pair(" ")
        assert await evaluate(session, "edit.value") == "aB1 "
        await perform(ActionType.KEY_DOWN, key="Ctrl")
        await key_pair("a")
        await perform(ActionType.KEY_UP, key="Ctrl")
        assert await evaluate(session, "edit.selectionEnd-edit.selectionStart") == 4
        for text in ["中文", " 日本語", " 😀"]:
            await perform(ActionType.TEXT_INPUT, text=text)
        await perform(ActionType.TEXT_INPUT, text="")
        assert await evaluate(session, "edit.value") == "中文 日本語 😀"
        await key_pair("Enter")
        await key_pair("x")
        await key_pair("Backspace")
        assert await evaluate(session, "edit.value") == "中文 日本語 😀\n"
        await key_pair("ArrowLeft")
        await key_pair("Delete")
        assert await evaluate(session, "edit.value") == "中文 日本語 😀"
        await key_pair("Escape")
        for modifier in ["Alt", "Meta"]:
            await perform(ActionType.KEY_DOWN, key=modifier)
            await key_pair("ArrowLeft")
            await perform(ActionType.KEY_UP, key=modifier)
        await key_pair("Tab")
        keyboard = await evaluate(session, "events")
        assert isinstance(keyboard, list)
        assert any(
            isinstance(e, dict) and e["type"] == "keydown" and e["key"] == "B" and e["shift"]
            for e in keyboard
        )
        assert any(
            isinstance(e, dict) and e["type"] == "keydown" and e["key"] == "a" and e["ctrl"]
            for e in keyboard
        )
        for modifier in ["alt", "meta"]:
            assert any(
                isinstance(e, dict)
                and e["type"] == "keydown"
                and e["key"] == "ArrowLeft"
                and e[modifier]
                for e in keyboard
            )
        report["keyboard_events"], report["fixture_value"] = (
            keyboard,
            await evaluate(session, "edit.value"),
        )

        identity = (session.page_id, session.session_id, session.generation)
        await session.send(
            "Page.navigate",
            {"url": "data:text/html;charset=utf-8," + quote(HTML + "<!-- navigated -->")},
        )
        await wait_fixture(session)
        assert identity == (session.page_id, session.session_id, session.generation)
        await perform(ActionType.MOUSE_CLICK, x=60, y=60, button="left")
        assert (
            await evaluate(session, "events.some(e=>e.type==='click' && e.target==='mark')") is True
        )
        report["navigation_identity_preserved"] = True
        await session.bind(targets[1])
        try:
            await provider.execute(Action(page_id=targets[0], type=ActionType.TEXT_INPUT, text=""))
        except ValidationError:
            report["old_target_rejected"] = True
        assert report.get("old_target_rejected") is True
        await session.send("Page.bringToFront")
        await wait_fixture(session)
        await perform(ActionType.MOUSE_CLICK, x=60, y=60, button="left")
        await perform(ActionType.KEY_DOWN, key="Shift")
        await provider.close()
        assert session.is_ready
        assert (
            await evaluate(session, "events.some(e=>e.type==='keyup' && e.key==='Shift')") is True
        )
        report["close_released_modifier"] = True
        await session.connection.send("Target.closeTarget", {"targetId": targets[1]})
        targets.pop()  # Do not close the same disposable target twice in finally.
        async with asyncio.timeout(5):
            while session.is_ready:
                await asyncio.sleep(0.01)
        replacement = BrowserInputProvider(session)
        try:
            await replacement.start()
        except CapabilityUnavailableError:
            report["closed_target_rejected"] = True
        await replacement.close()
        assert report.get("closed_target_rejected") is True
        report["timings_ms"] = {
            kind: {"count": len(values), "median": median(values), "samples": list(values)}
            for kind, values in samples.items()
        }
        report["status"] = "passed"
    except BaseException as exc:
        report["status"], report["failure_type"] = "failed", type(exc).__name__
        raise
    finally:
        await provider.close()
        await capture.close()
        for target in targets:
            with suppress(BrowserError):
                await session.connection.send("Target.closeTarget", {"targetId": target})
        await session.close()
        report["cleanup"] = {
            "pending_count": session.connection.pending_count,
            "reader_running": session.connection.reader_running,
            "connected": session.connected,
        }
        (output / "input-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.environ.get("BCA_CDP_ENDPOINT"))
    parser.add_argument("--output", type=Path, default=Path("input-artifacts"))
    args = parser.parse_args()
    if not args.endpoint:
        parser.error("--endpoint or BCA_CDP_ENDPOINT is required")
    report = asyncio.run(run_input_checks(args.endpoint, args.output))
    print(
        json.dumps(
            {
                "status": report["status"],
                "timings_ms": report["timings_ms"],
                "cleanup": report["cleanup"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
