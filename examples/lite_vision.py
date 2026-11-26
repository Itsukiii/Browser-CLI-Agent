"""Owned Edge fixture smoke, with explicitly provisioned OCR and no old Vision backend.

python examples/lite_vision.py --endpoint http://127.0.0.1:9341 \
    --model ABSOLUTE_MODEL_DIRECTORY --manifest ABSOLUTE_MANIFEST_JSON
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
from pathlib import Path
from urllib.parse import quote

from bca.core.browser import BrowserCaptureProvider, BrowserInputProvider, BrowserSession
from bca.lite.bridge import CDPBridge
from bca.lite.fixture import FixturePlugin, fixture_bundle, fixture_html
from bca.lite.observation import ObservationCoordinator
from bca.lite.vision import MaaVisionFacade
from bca.lite.vision_resources import OCRModelSpec, ResourceSpec
from bca.lite.vision_types import RecognitionStatus


async def main(endpoint: str, model: Path, manifest: Path) -> None:
    session = BrowserSession(endpoint)
    capture, inputs = BrowserCaptureProvider(session), BrowserInputProvider(session)
    target: str | None = None
    coordinator: ObservationCoordinator | None = None
    await session.connect()
    original = {t.target_id for t in await session.list_targets()}
    with fixture_bundle() as bundle:
        try:
            target = str(
                (
                    await session.connection.send(
                        "Target.createTarget",
                        {
                            "url": "data:text/html;charset=utf-8," + quote(fixture_html(bundle)),
                        },
                    )
                )["targetId"]
            )
            await session.bind(target)
            await session.send(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": 640,
                    "height": 400,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
            )
            await session.send("Page.bringToFront")
            async with asyncio.timeout(10):
                while True:
                    ready = await session.send(
                        "Runtime.evaluate",
                        {
                            "expression": "document.images.length===2 && "
                            "[...document.images].every(i=>i.complete)",
                            "returnByValue": True,
                        },
                    )
                    result_value = ready.get("result")
                    if isinstance(result_value, dict) and result_value.get("value"):
                        break
                    await asyncio.sleep(0.05)
            await capture.start()
            await inputs.start()
            resources = ResourceSpec(bundle, OCRModelSpec(model.resolve(), manifest.resolve()))
            bridge = CDPBridge(
                loop=asyncio.get_running_loop(),
                session=session,
                capture=capture,
                input_provider=inputs,
                require_authorization=True,
                max_frame_age=5,
            )
            coordinator = ObservationCoordinator(
                MaaVisionFacade(bridge, resources), FixturePlugin(resources), interval=1
            )
            await coordinator.start()
            first = await coordinator.refresh()
            assert first.state.status == RecognitionStatus.MATCHED
            assert first.state.interaction_revision == "123"
            result = await coordinator.execute_text("click 123")
            assert result.outcome == "confirmed"
            assert result.observation.state.interaction_revision == "124"
            oracle = await session.send(
                "Runtime.evaluate",
                {
                    "expression": "hits",
                    "returnByValue": True,
                },
            )
            oracle_result = oracle["result"]
            assert isinstance(oracle_result, dict)
            hits = oracle_result["value"]
            assert isinstance(hits, list) and len(hits) == 1
            assert isinstance(hits[0], dict) and hits[0]["id"] == "button"
            print(
                json.dumps(
                    {
                        "outcome": result.outcome,
                        "payload": result.observation.state.payload,
                        "oracle": oracle,
                        "resource": str(bundle),
                    },
                    indent=2,
                )
            )
        finally:
            if coordinator is not None:
                report = await coordinator.aclose()
                print(json.dumps({"native_close": dataclasses.asdict(report)}))
                if not report.released:
                    raise RuntimeError("native cleanup incomplete; providers must remain alive")
            await inputs.close()
            await capture.close()
            if target:
                await session.connection.send("Target.closeTarget", {"targetId": target})
                async with asyncio.timeout(5):
                    while target in {t.target_id for t in await session.list_targets()}:
                        await asyncio.sleep(0.02)
            assert original.issubset({t.target_id for t in await session.list_targets()})
            await session.close()
            assert session.connection.pending_count == 0
            assert not session.connection.reader_running


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    options = parser.parse_args()
    asyncio.run(main(options.endpoint, options.model, options.manifest))
