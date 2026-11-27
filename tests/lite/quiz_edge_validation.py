"""Sequential owned Edge fault/zoom/performance validation. DOM is oracle only."""

import asyncio
import dataclasses
import json
import os
import statistics
import sys
import time
from pathlib import Path
from urllib.parse import quote

from PIL import Image

from bca.core.browser import BrowserCaptureProvider, BrowserInputProvider, BrowserSession
from bca.lite.bridge import CDPBridge
from bca.lite.quiz import QuizPlugin, decode_quiz_state
from bca.lite.quiz_assets import quiz_html, quiz_vision_bundle
from bca.lite.vision import MaaVisionFacade
from bca.lite.vision_resources import ResourceSpec
from bca.lite.vision_types import OCRRequest, RecognitionStatus
from examples.browser_end_to_end import evaluate
from tests.lite.test_real_addendum import TITLE, desktop_key, finish, metrics
from tests.lite.test_vision_native import model_spec, result_record


def equivalent(state, oracle):
    data = decode_quiz_state(state)
    return (data.round_mark, data.question, list(data.options), data.score, data.selected) == (
        oracle["round"],
        oracle["question"],
        oracle["options"],
        int(oracle["score"]),
        None if oracle["selected"] is None else "ABCD"[oracle["selected"]],
    )


async def run(output, mode, bundle):
    output.mkdir(parents=True, exist_ok=False)
    session = BrowserSession(os.environ["BCA_CDP_ENDPOINT"])
    capture, inputs = BrowserCaptureProvider(session), BrowserInputProvider(session)
    target = facade = None
    report = dict(
        mode=mode,
        rows=[],
        shortcuts=[],
        viewport=os.environ.get("BCA_QUIZ_VIEWPORT", "native-window"),
        raw=not bool(os.environ.get("BCA_QUIZ_NONRAW")),
    )
    await session.connect()
    original = {t.target_id for t in await session.list_targets()}
    capture_times, native_times = [], []
    try:
        target = (
            await session.connection.send(
                "Target.createTarget",
                {
                    "url": "data:text/html;charset=utf-8,"
                    + quote(
                        quiz_html(bundle).replace(
                            "<title>BCA Quiz</title>", f"<title>{TITLE}</title>"
                        )
                    )
                    + ("#seed=55391" if mode == "performance" else "#seed=55391&test=1"),
                    "newWindow": True,
                },
            )
        )["targetId"]
        await session.bind(target)
        if os.environ.get("BCA_QUIZ_VIEWPORT") == "960x640":
            await session.send(
                "Emulation.setDeviceMetricsOverride",
                {"width": 960, "height": 640, "deviceScaleFactor": 1, "mobile": False},
            )
        await session.send("Page.bringToFront")
        async with asyncio.timeout(10):
            while not await evaluate(session, "document.querySelector('#question img')!==null"):
                await asyncio.sleep(0.05)
        await capture.start()
        await inputs.start()
        bridge = CDPBridge(
            loop=asyncio.get_running_loop(),
            session=session,
            capture=capture,
            input_provider=inputs,
            require_authorization=True,
            max_frame_age=2,
        )
        plugin = QuizPlugin(ResourceSpec(bundle, model_spec()))
        facade = MaaVisionFacade(bridge, plugin.resources, raw_size=report["raw"])
        await facade.start()
        native = facade._native
        capture_original, recognize_original = native.capture, native.recognize

        def timed_capture():
            start = time.monotonic()
            try:
                return capture_original()
            finally:
                capture_times.append(time.monotonic() - start)

        def timed_recognize(request, image):
            start = time.monotonic()
            try:
                return recognize_original(request, image)
            finally:
                native_times.append(time.monotonic() - start)

        native.capture, native.recognize = timed_capture, timed_recognize

        async def oracle():
            return await evaluate(
                session,
                """({round:document.querySelector('#round').textContent,
              question:Number(document.querySelector('#question img')?.alt),
              options:[...document.querySelectorAll('.value img')].map(i=>Number(i.alt)),
              score:document.querySelector('#score').textContent,
              selected:[...document.querySelectorAll('.option')].findIndex(i=>i.classList.contains('selected'))})""",
            )

        async def observe(label, negative=False):
            before = await oracle()
            before["selected"] = None if before["selected"] == -1 else before["selected"]
            n = len(native_times)
            start = time.monotonic()
            batch = await facade.recognize(plugin.plan)
            parse = time.monotonic()
            state = plugin.observe(batch)
            end = time.monotonic()
            after = await oracle()
            after["selected"] = None if after["selected"] == -1 else after["selected"]
            matched = state.status == RecognitionStatus.MATCHED
            correct = matched and (equivalent(state, before) or equivalent(state, after))
            row = dict(
                label=label,
                before=before,
                after=after,
                negative=negative,
                state=dataclasses.asdict(state),
                correct=correct,
                valid=correct and batch.source_current and not batch.expired,
                capture=capture_times[-1],
                native=sum(native_times[n:]),
                native_per_request=native_times[n:],
                parse=end - parse,
                total=end - start,
                requests=[
                    dataclasses.asdict(r)
                    for r in plugin.plan((batch.capture.width, batch.capture.height))
                ],
                **result_record(batch),
            )
            index = len(report["rows"])
            (output / f"input-{index}.png").write_bytes(batch.capture.source_ref.frame.data)
            Image.fromarray(batch.capture.image[:, :, ::-1]).save(output / f"maa-{index}.png")
            report["rows"].append(row)
            with (output / "rows.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row) + "\n")
            return row

        if mode == "performance":
            start = time.monotonic()
            while time.monotonic() - start < 60:
                await observe("continuous-real-clock")
            report["elapsed"] = time.monotonic() - start
            report["valid_hz"] = sum(r["valid"] for r in report["rows"]) / report["elapsed"]
            for field in ("capture", "native", "parse", "total"):
                values = sorted(r[field] for r in report["rows"])
                report[field] = dict(
                    median=statistics.median(values), p95=values[int(0.95 * (len(values) - 1))]
                )
        elif mode == "zoom":
            report["shortcuts"].append(desktop_key(0x30))
            await asyncio.sleep(0.4)
            baseline = await metrics(session)
            report["baseline"] = baseline
            for percent, keys in [(80, [0xBD, 0xBD]), (100, []), (125, [0xBB, 0xBB])]:
                report["shortcuts"].append(desktop_key(0x30))
                for key in keys:
                    report["shortcuts"].append(desktop_key(key))
                await asyncio.sleep(0.4)
                measured = await metrics(session)
                ratio = measured["runtime"]["dpr"] / baseline["runtime"]["dpr"]
                assert abs(ratio - percent / 100) < 0.02
                seen = set()
                for _ in range(10):
                    for _attempt in range(200):
                        value = await evaluate(session, "quizTest.advance(10000)")
                        if value["question"] not in seen:
                            seen.add(value["question"])
                            break
                    else:
                        raise AssertionError("zoom digit coverage incomplete")
                    row = await observe(f"zoom-{percent}")
                    row["metrics"] = measured
            report["shortcuts"].append(desktop_key(0x30))
        else:
            # No page rules altered. Temporary visual defects on an owned test page only.
            original_html = await evaluate(session, "document.getElementById('question').innerHTML")
            for label, script in [
                ("blur", "q.style.filter='blur(7px)'"),
                ("low-contrast", "q.style.opacity='.03'"),
                ("occluded", "q.style.clipPath='inset(0 60% 0 0)'"),
                ("roi-shift", "q.style.left='200px'"),
                ("duplicate", "q.innerHTML+=q.innerHTML"),
                ("unsupported-font-56", "q.textContent='1';q.style.fontSize='56px'"),
            ]:
                await evaluate(
                    session, "{const q=document.getElementById('question');" + script + "}"
                )
                await observe(label, True)
                await evaluate(
                    session,
                    "{const q=document.getElementById('question');"
                    "q.removeAttribute('style');q.innerHTML=" + json.dumps(original_html) + "}",
                )
            full = await facade.recognize((OCRRequest("full-image-diagnostic", unique=False),))
            (output / "full-image.json").write_text(
                json.dumps(result_record(full), indent=2), encoding="utf-8"
            )
            Image.fromarray(full.capture.image[:, :, ::-1]).save(output / "full-image.png")
        report["wrong_matched"] = sum(
            r["state"]["status"] == "MATCHED" and not r["correct"] for r in report["rows"]
        )
        report["negative_matched"] = sum(
            r["negative"] and r["state"]["status"] == "MATCHED" for r in report["rows"]
        )
        report["valid_count"] = sum(r["valid"] for r in report["rows"])
    finally:
        if facade:
            report["close"] = dataclasses.asdict(await facade.aclose())
        try:
            await finish(session, capture, inputs, target, original, report)
        finally:
            (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert report["wrong_matched"] == 0 and report["negative_matched"] == 0
    if mode == "performance":
        assert report["valid_hz"] >= 1
    if mode == "zoom":
        assert report["valid_count"] / len(report["rows"]) >= 0.95


if __name__ == "__main__":
    if os.environ.get("BCA_QUIZ_AFFINITY"):
        import psutil

        process = psutil.Process()
        permitted = process.cpu_affinity()
        selected = permitted[: int(os.environ["BCA_QUIZ_AFFINITY"])]
        process.cpu_affinity(selected)
        print(json.dumps({"actual_pid": process.pid, "test_only_cpu_affinity": selected}))
    with quiz_vision_bundle() as bundle:
        asyncio.run(run(Path(sys.argv[1]), sys.argv[2], bundle))
