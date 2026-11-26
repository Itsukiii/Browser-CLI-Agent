"""Standalone installed-wheel probe: no pytest, repo resources, cv2 or test helpers."""

import importlib.metadata
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
from maa.library import Library
from PIL import Image, ImageDraw, ImageFont

import bca
from bca.lite._native_vision import NativeVision
from bca.lite.fixture import fixture_bundle, fixture_html
from bca.lite.vision_resources import OCRModelSpec, ResourceSpec
from bca.lite.vision_types import OCRRequest, RecognitionStatus, TemplateRequest, VisionError


def main():
    model = OCRModelSpec(Path(sys.argv[1]), Path(sys.argv[2]))
    model.verify()
    assert "site-packages" in bca.__file__
    report = {
        "cwd": str(Path.cwd()),
        "bca": bca.__file__,
        "python": sys.version,
        "maa": Library.version(),
        "distribution": importlib.metadata.version("maafw"),
    }
    with fixture_bundle() as bundle:
        report["bundle"] = str(bundle)
        assert "MARKER_DATA" not in fixture_html(bundle)
        image = Image.new("RGB", (640, 400), "white")
        with Image.open(bundle / "image/marker.png") as marker:
            image.paste(marker, (60, 50))
        ImageDraw.Draw(image).text((80, 240), "123", fill="black", font=ImageFont.load_default(48))

        class StaticBridge:
            connected = True
            bound_page_id = "wheel-static-fixture"

            def screencap(self):
                return np.asarray(image)[:, :, ::-1].copy()

        for with_model in (True, False):
            owner = NativeVision(
                StaticBridge(), ResourceSpec(bundle, model if with_model else None), True
            )
            try:
                owner.start()
                pixels = owner.capture()
                template = owner.recognize(TemplateRequest("button", "marker.png"), pixels)
                ocr = owner.recognize(OCRRequest("round", roi=(0, 200, 640, 200)), pixels)
                assert template.status == RecognitionStatus.MATCHED
                assert template.candidates[0].box == (60, 50, 96, 64)
                if with_model:
                    assert ocr.status == RecognitionStatus.MATCHED
                    assert ocr.candidates[0].text == "123"
                else:
                    assert (
                        ocr.status == RecognitionStatus.ERROR and "model" in ocr.diagnostic.lower()
                    )
                report[str(with_model)] = {
                    "template": template.raw_detail_json,
                    "ocr": ocr.raw_detail_json,
                    "diagnostic": ocr.diagnostic,
                }
            finally:
                close = owner.close()
                assert close.released and close.destroyed == ("tasker", "controller", "resource")
        missing = OCRModelSpec(model.directory / "absent", model.manifest)
        try:
            missing.verify()
        except VisionError:
            report["missing_model_rejected"] = True
        else:
            raise AssertionError("missing model accepted")
        with tempfile.TemporaryDirectory(prefix="bca-model-check-") as folder:
            copied = Path(folder) / "ocr"
            shutil.copytree(model.directory, copied)
            keys = copied / "keys.txt"
            data = keys.read_bytes()
            keys.write_bytes(bytes([data[0] ^ 1]) + data[1:])
            try:
                OCRModelSpec(copied, model.manifest).verify()
            except VisionError as exc:
                assert "SHA256" in str(exc)
                report["corrupt_model_rejected"] = str(exc)
            else:
                raise AssertionError("corrupt model accepted")
    assert "cv2" not in sys.modules and "bca.plugin_sdk.vision" not in sys.modules
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
