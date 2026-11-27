"""04.2 initial real Maa OCR probe on recorded owned Edge screenshots."""

import asyncio
import json
import os
import time
from pathlib import Path

import pytest
from PIL import Image

pytest.importorskip("maa")
from bca.lite.vision import MaaVisionFacade
from bca.lite.vision_resources import ResourceSpec
from bca.lite.vision_types import OCRRequest
from tests.lite.test_vision_native import model_spec, result_record
from tests.lite.vision_fixture import bridge_for, bundle_at


def test_quiz_ocr_probe(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    output = Path(os.environ.get("BCA_QUIZ_EVIDENCE", str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    rows = []

    async def run():
        with Image.open(root / "docs/evidence/LITE-04/04.1/edge-02/score--305.png") as src:
            image = src.convert("RGB")
        bridge, _, _, _ = bridge_for(monkeypatch, image, max_frame_age=10)
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle_at(tmp_path / "bundle"), model_spec()))
        await facade.start()
        try:
            requests = (
                OCRRequest("round", (80, 45, 400, 65)),
                OCRRequest("time", (720, 45, 180, 65)),
                OCRRequest("question", (380, 145, 200, 90)),
                OCRRequest("score", (80, 515, 380, 70)),
            )
            requests += tuple(
                OCRRequest("option_" + str(i), (100 + i * 220, 335, 100, 80)) for i in range(4)
            )
            for _ in range(3):
                started = time.monotonic()
                batch = await facade.recognize(requests)
                rows.append({"seconds": time.monotonic() - started, **result_record(batch)})
        finally:
            assert (await facade.aclose()).released

    try:
        asyncio.run(run())
    finally:
        (output / "ocr-probe.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


def test_quiz_failed_digit_modes(tmp_path, monkeypatch):
    """Diagnostic only: does only_rec fix recorded failures without changing pixels?"""
    root = Path(__file__).resolve().parents[2]
    output = Path(os.environ.get("BCA_QUIZ_EVIDENCE", str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    records = []

    async def run():
        for path, expected in [
            ("edge-01/dpr-2-raw-True/input-3.png", "6"),
            ("font-probe-01/dpr-2-raw-True/input-0.png", "1"),
        ]:
            with Image.open(root / "docs/evidence/LITE-04/04.2" / path) as source:
                pixels = source.convert("RGB")
            bridge, _, _, _ = bridge_for(monkeypatch, pixels, max_frame_age=10)
            facade = MaaVisionFacade(
                bridge, ResourceSpec(bundle_at(tmp_path / str(len(records))), model_spec())
            )
            await facade.start()
            try:
                batch = await facade.recognize(
                    tuple(
                        OCRRequest(f"mode-{mode}", (760, 290, 400, 180), only_rec=mode)
                        for mode in (False, True)
                    )
                )
                records.append(dict(path=path, expected=expected, **result_record(batch)))
            finally:
                assert (await facade.aclose()).released

    try:
        asyncio.run(run())
    finally:
        (output / "digit-modes.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
