"""Actual Edge screenshots and Maa Template/OCR; DOM is an independent oracle."""

import asyncio
import dataclasses
import json
import os
import time
from pathlib import Path
from urllib.parse import quote

import pytest
from PIL import Image

pytest.importorskip("maa")
from bca.core.browser import BrowserCaptureProvider, BrowserInputProvider, BrowserSession
from bca.lite.bridge import CDPBridge
from bca.lite.quiz import QuizPlugin, decode_quiz_state
from bca.lite.quiz_assets import quiz_html, quiz_vision_bundle
from bca.lite.vision import MaaVisionFacade
from bca.lite.vision_resources import ResourceSpec
from bca.lite.vision_types import RecognitionStatus
from examples.browser_end_to_end import evaluate
from tests.lite.test_real_addendum import finish
from tests.lite.test_vision_native import model_spec, result_record

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(
        not os.environ.get("BCA_CDP_ENDPOINT"), reason="explicit isolated Edge required"
    ),
]


@pytest.mark.parametrize(
    "dpr,raw", [(1, True), (1.5, True), (2, True), (1, False), (1.5, False), (2, False)]
)
@pytest.mark.parametrize(
    "seed", [9173, 60127, 88219] if os.environ.get("BCA_QUIZ_BLIND") else [20261127]
)
def test_quiz_native_fields(tmp_path, dpr, raw, seed):
    blind = bool(os.environ.get("BCA_QUIZ_BLIND"))
    suffix = f"-seed-{seed}" if blind else ""
    output = (
        Path(os.environ.get("BCA_QUIZ_EVIDENCE", str(tmp_path))) / f"dpr-{dpr}-raw-{raw}{suffix}"
    )
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "dpr": dpr,
        "raw": raw,
        "seed": seed,
        "blind": blind,
        "rows": [],
        "probe_font": os.environ.get("BCA_QUIZ_PROBE_FONT"),
        "requests": [],
    }

    async def run(bundle):
        session = BrowserSession(os.environ["BCA_CDP_ENDPOINT"])
        capture, inputs = BrowserCaptureProvider(session), BrowserInputProvider(session)
        target = facade = None
        await session.connect()
        original = {t.target_id for t in await session.list_targets()}
        try:
            target = (
                await session.connection.send(
                    "Target.createTarget",
                    {
                        "url": "data:text/html;charset=utf-8,"
                        + quote(quiz_html(bundle))
                        + f"#test=1&seed={seed}&glyph={'bold' if seed == 60127 else 'normal'}"
                    },
                )
            )["targetId"]
            await session.bind(target)
            await session.send(
                "Emulation.setDeviceMetricsOverride",
                {"width": 960, "height": 640, "deviceScaleFactor": dpr, "mobile": False},
            )
            await session.send("Page.bringToFront")
            async with asyncio.timeout(5):
                while not await evaluate(session, "typeof quizTest==='object'"):
                    await asyncio.sleep(0.02)
            await capture.start()
            await inputs.start()
            bridge = CDPBridge(
                loop=asyncio.get_running_loop(),
                session=session,
                capture=capture,
                input_provider=inputs,
                require_authorization=True,
                max_frame_age=3,
            )
            plugin = QuizPlugin(ResourceSpec(bundle, model_spec()))
            facade = MaaVisionFacade(bridge, plugin.resources, raw_size=raw)
            await facade.start()
            seen = set()
            correct = 0
            scores = ["0", "-1", "-20", "-305", "12", "345", "6789"]
            for i in range(10 if blind else 7):
                score = scores[i % len(scores)]
                await evaluate(
                    session,
                    f"quizTest.advance(10000);quizTest.set({{newScore:{json.dumps(score)}}})",
                )
                if blind:
                    for _ in range(200):
                        candidate = await evaluate(session, "quizTest.snapshot()")
                        if candidate["question"] not in seen:
                            seen.add(candidate["question"])
                            break
                        await evaluate(session, "quizTest.advance(10000)")
                    else:
                        raise AssertionError("seed did not cover ten digits")
                if i % 2:
                    await evaluate(
                        session, f"document.getElementById('option_{'ABCD'[i % 4]}').click()"
                    )
                expected = await evaluate(session, "quizTest.snapshot()")
                if os.environ.get("BCA_QUIZ_PROBE_FONT"):
                    await evaluate(
                        session,
                        "{const q=document.getElementById('question');"
                        "q.textContent=q.querySelector('img').alt;q.style.fontSize='56px'}",
                    )
                started = time.monotonic()
                batch = await facade.recognize(plugin.plan)
                report["requests"] = [
                    dataclasses.asdict(r)
                    for r in plugin.plan((batch.capture.width, batch.capture.height))
                ]
                state = plugin.observe(batch)
                report["rows"].append(
                    {
                        "seconds": time.monotonic() - started,
                        "expected": expected,
                        "state": dataclasses.asdict(state),
                        **result_record(batch),
                    }
                )
                (output / f"input-{i}.png").write_bytes(batch.capture.source_ref.frame.data)
                Image.fromarray(batch.capture.image[:, :, ::-1]).save(output / f"maa-{i}.png")
                if blind and state.status != RecognitionStatus.MATCHED:
                    assert not state.targets
                    continue
                assert state.status == RecognitionStatus.MATCHED, report["rows"][-1]
                data = decode_quiz_state(state)
                assert (
                    data.round_mark,
                    data.question,
                    list(data.options),
                    data.score,
                    data.selected,
                ) == (
                    expected["round"],
                    expected["question"],
                    expected["options"],
                    int(score),
                    None if expected["selected"] is None else "ABCD"[expected["selected"]],
                )
                correct += 1
            report["correct"] = correct
            report["coverage"] = sorted(seen)
            if blind:
                assert correct / len(report["rows"]) >= 0.95
            report["status"] = "passed"
        finally:
            if facade:
                report["close"] = dataclasses.asdict(await facade.aclose())
                assert report["close"]["released"]
            try:
                await finish(session, capture, inputs, target, original, report)
            finally:
                (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    with quiz_vision_bundle() as bundle:
        asyncio.run(run(bundle))
