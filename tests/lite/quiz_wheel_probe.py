"""Run with an independently installed wheel from an unrelated cwd."""

import hashlib
import json
import sys
from importlib.metadata import version
from pathlib import Path

import bca.lite.quiz as quiz
from bca.lite.quiz_assets import quiz_html, quiz_vision_bundle
from bca.lite.vision_resources import OCRModelSpec, ResourceSpec

model = OCRModelSpec(Path(sys.argv[1]), Path(sys.argv[2]))
assert "site-packages" in quiz.__file__
with quiz_vision_bundle() as bundle:
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
assert not bundle.exists()
report["temporary_resources_removed"] = True
print(json.dumps(report, indent=2))
