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
def test_quiz_native_fields(tmp_path, dpr, raw):
    output = Path(os.environ.get("BCA_QUIZ_EVIDENCE", str(tmp_path))) / f"dpr-{dpr}-raw-{raw}"
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "dpr": dpr,
        "raw": raw,
        "rows": [],
        "probe_font": os.environ.get("BCA_QUIZ_PROBE_FONT"),
        "ocr_threshold": 0.9,
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
                        + "#test=1&seed=20261127"
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
            if os.environ.get("BCA_QUIZ_PROBE_FONT"):
                await evaluate(
                    session,
                    "document.getElementById('question').style.fontSize='56px'",
                )
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
            for i, score in enumerate(["0", "-1", "-20", "-305", "12", "345", "6789"]):
                await evaluate(
                    session,
                    f"quizTest.advance(10000);quizTest.set({{newScore:{json.dumps(score)}}})",
                )
                if i % 2:
                    await evaluate(
                        session, f"document.getElementById('option_{'ABCD'[i % 4]}').click()"
                    )
                expected = await evaluate(session, "quizTest.snapshot()")
                started = time.monotonic()
                batch = await facade.recognize(plugin.plan)
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
            report["status"] = "passed"
        finally:
            if facade:
                report["close"] = dataclasses.asdict(await facade.aclose())
                assert report["close"]["released"]
            await finish(session, capture, inputs, target, original, report)
            (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    with quiz_vision_bundle() as bundle:
        asyncio.run(run(bundle))
