"""Repeated native close probe; records stop/running timing without changing native state."""

# ruff: noqa: E402
import asyncio
import dataclasses
import json
import os
import time
from pathlib import Path

import pytest

pytest.importorskip("maa")
from maa.tasker import Tasker

from bca.lite.vision import MaaVisionFacade
from bca.lite.vision_resources import ResourceSpec
from bca.lite.vision_types import OCRRequest
from tests.lite.test_vision_native import model_spec
from tests.lite.vision_fixture import bridge_for, bundle_at, scene


def test_native_stop_settlement(tmp_path, monkeypatch):
    records = []
    original = Tasker.running.fget

    def running(tasker):
        value = original(tasker)
        records.append({"event": "running", "value": value, "at": time.monotonic()})
        return value

    monkeypatch.setattr(Tasker, "running", property(running))

    async def run():
        bundle = bundle_at(tmp_path / "bundle")
        model = model_spec()
        for index in range(int(os.environ.get("BCA_STOP_ROUNDS", "10"))):
            bridge, _, _, _ = bridge_for(monkeypatch, scene("-20"), max_frame_age=10)
            facade = MaaVisionFacade(bridge, ResourceSpec(bundle, model))
            await facade.start()
            await facade.recognize((OCRRequest("full"), OCRRequest("roi", (50, 100, 350, 110))))
            report = await facade.aclose()
            records.append(
                {
                    "event": "close",
                    "round": index,
                    "at": time.monotonic(),
                    "report": dataclasses.asdict(report),
                }
            )
            if not report.released:
                await asyncio.sleep(0.01)
                report = await facade.aclose()
                records.append(
                    {
                        "event": "retry",
                        "round": index,
                        "at": time.monotonic(),
                        "report": dataclasses.asdict(report),
                    }
                )
            assert report.released

    try:
        asyncio.run(run())
    finally:
        root = Path(os.environ.get("BCA_VISION_EVIDENCE", str(tmp_path)))
        root.mkdir(parents=True, exist_ok=True)
        (root / "stop-settlement.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
