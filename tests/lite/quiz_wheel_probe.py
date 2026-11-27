"""Run with an independently installed wheel from an unrelated cwd."""

import asyncio
import dataclasses
import hashlib
import json
import sys
from importlib.metadata import version
from pathlib import Path
from urllib.parse import quote

import bca.lite.quiz as quiz
from bca.core.browser import BrowserCaptureProvider, BrowserInputProvider, BrowserSession
from bca.lite.bridge import CDPBridge
from bca.lite.quiz_assets import quiz_html, quiz_vision_bundle
from bca.lite.vision import MaaVisionFacade
from bca.lite.vision_resources import OCRModelSpec, ResourceSpec

model = OCRModelSpec(Path(sys.argv[1]), Path(sys.argv[2]))


async def native_probe(resource):
    session = BrowserSession(sys.argv[3])
    capture, inputs = BrowserCaptureProvider(session), BrowserInputProvider(session)
    target = facade = None
    result = {}
    await session.connect()
    original = {t.target_id for t in await session.list_targets()}
    try:
        target = (
            await session.connection.send(
                "Target.createTarget",
                {
                    "url": "data:text/html;charset=utf-8,"
                    + quote(quiz_html(resource.bundle))
                    + "#test=1&seed=737"
                },
            )
        )["targetId"]
        await session.bind(target)
        await session.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": 960, "height": 640, "deviceScaleFactor": 1, "mobile": False},
        )
        await capture.start()
        await inputs.start()
        async with asyncio.timeout(10):
            while True:
                value = await session.send(
                    "Runtime.evaluate",
                    {"expression": "typeof quizTest==='object'", "returnByValue": True},
                )
                if value["result"].get("value"):
                    break
                await asyncio.sleep(0.05)
        facade = MaaVisionFacade(
            CDPBridge(
                loop=asyncio.get_running_loop(),
                session=session,
                capture=capture,
                input_provider=inputs,
                require_authorization=True,
            ),
            resource,
        )
        await facade.start()
        plugin = quiz.QuizPlugin(resource)
        batch = await facade.recognize(plugin.plan)
        data = quiz.decode_quiz_state(plugin.observe(batch))
        result["snapshot"] = dataclasses.asdict(data)
        result["frame"] = batch.capture.source_ref.frame.frame_id
        assert batch.source_current
        result["expired"] = batch.expired  # Packaging success does not waive the performance gate.
        oracle = await session.send(
            "Runtime.evaluate", {"expression": "quizTest.snapshot()", "returnByValue": True}
        )
        oracle = oracle["result"]["value"]
        assert (data.question, list(data.options), data.round_mark, data.score) == (
            oracle["question"],
            oracle["options"],
            oracle["round"],
            int(oracle["score"]),
        )
        broken = OCRModelSpec(model.directory, resource.bundle / "absent.json")
        try:
            broken.verify()
        except Exception as exc:
            result["bad_model_rejected"] = type(exc).__name__
        else:
            raise AssertionError("missing manifest accepted")
    finally:
        if facade:
            result["close"] = dataclasses.asdict(await facade.aclose())
            assert result["close"]["released"] and resource.bundle.exists()
        await inputs.close()
        await capture.close()
        if target:
            await session.connection.send("Target.closeTarget", {"targetId": target})
        assert original.issubset({t.target_id for t in await session.list_targets()})
        await session.close()
        result["pending"] = session.connection.pending_count
        result["reader"] = session.connection.reader_running
        assert not result["pending"] and not result["reader"]
    return result


assert "site-packages" in quiz.__file__
with quiz_vision_bundle() as bundle:
    packaged_manifest = bundle / "ocr-model.json"
    assert packaged_manifest.read_bytes() == model.manifest.read_bytes()
    model = OCRModelSpec(model.directory, packaged_manifest)
    resource = ResourceSpec(bundle, model)
    assert resource.ocr.verify() == model.directory
    assert "data:image/png;base64," in quiz_html(bundle)
    assert len(quiz.QuizPlugin(resource).plan((1920, 1280))) == 67
    report = {
        "module": quiz.__file__,
        "python": sys.version,
        "maa": version("maafw"),
        "templates": len(list((bundle / "image").glob("*.png"))),
        "model_verified": True,
        "assets": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (bundle / "image").glob("*.png")
            if "-" not in p.name
        },
    }
    if len(sys.argv) > 3:
        report["native"] = asyncio.run(native_probe(resource))
assert not bundle.exists()
report["temporary_resources_removed"] = True
print(json.dumps(report, indent=2))
