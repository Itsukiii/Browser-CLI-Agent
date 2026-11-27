"""04.2a: native-only diagnostic comparison, not an Edge acceptance test."""

import asyncio
import dataclasses
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

from bca.lite.quiz_assets import quiz_vision_bundle
from bca.lite.vision import MaaVisionFacade
from bca.lite.vision_resources import ResourceSpec
from bca.lite.vision_types import OCRRequest, TemplateRequest
from tests.lite.generate_quiz_glyphs import render
from tests.lite.test_vision_native import model_spec, result_record
from tests.lite.vision_fixture import bridge_for


async def run(output, bundle):
    output.mkdir(parents=True, exist_ok=False)
    samples = []
    root = Path(__file__).resolve().parents[2]
    for path, truth in [
        ("edge-01/dpr-2-raw-True/input-3.png", 6),
        ("font-probe-01/dpr-2-raw-True/input-0.png", 1),
    ]:
        source = root / "docs/evidence/LITE-04/04.2" / path
        with Image.open(source) as image:
            pixels = image.convert("RGB")
        for height in (96, 112, 128, 144, 160):
            for weight in ("normal", "bold"):
                samples.append((pixels, truth, height, weight, (760, 290, 400, 180), str(source)))
    for height in (48, 56, 64, 72, 80):
        for weight in ("normal", "bold"):
            for digit in range(10):
                image = Image.new("RGB", (128, 128), "white")
                image.paste(render(digit, weight, height), (32, 16))
                samples.append(
                    (image, digit, height, weight, (24, 8, 72, 104), "original-path-render")
                )
    for height in {s[2] for s in samples}:
        for weight in ("normal", "bold"):
            for digit in range(10):
                render(digit, weight, height).save(
                    bundle / f"image/probe-{weight}-{digit}-{height}.png"
                )
    records = []
    with pytest.MonkeyPatch.context() as patch:
        bridge, capture, _, _ = bridge_for(patch, samples[0][0], max_frame_age=10)
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle, model_spec()))
        await facade.start()
        try:
            for index, (pixels, truth, height, weight, roi, source) in enumerate(samples):
                capture.image = pixels
                template_weight = "normal" if os.environ.get("BCA_CROSS_WEIGHT") else weight
                requests = (
                    OCRRequest("det", roi, threshold=0),
                    OCRRequest("rec", roi, threshold=0, only_rec=True),
                ) + tuple(
                    TemplateRequest(
                        f"digit-{digit}",
                        f"probe-{template_weight}-{digit}-{height}.png",
                        roi,
                        threshold=0.5,
                        unique=False,
                    )
                    for digit in range(10)
                )
                start = time.monotonic()
                batch = await facade.recognize(requests)
                scores = sorted(
                    [
                        (
                            max((c.score for c in r.all_candidates), default=0),
                            int(r.request_key.split("-")[1]),
                        )
                        for r in batch.results[2:]
                    ],
                    reverse=True,
                )
                row = dict(
                    index=index,
                    source=source,
                    truth=truth,
                    height=height,
                    weight=weight,
                    seconds=time.monotonic() - start,
                    roi=roi,
                    requests=[dataclasses.asdict(r) for r in requests],
                    ranking=scores,
                    margin=scores[0][0] - scores[1][0],
                    **result_record(batch),
                )
                pixels.save(output / f"input-{index}.png")
                row["sha256"] = hashlib.sha256(
                    (output / f"input-{index}.png").read_bytes()
                ).hexdigest()
                records.append(row)
                with (output / "rows.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row) + "\n")
        finally:
            close = dataclasses.asdict(await facade.aclose())
            (output / "close.json").write_text(json.dumps(close, indent=2), encoding="utf-8")
            assert close["released"]
    confusion = {}
    for group in ("historical", "controlled"):
        confusion[group] = {}
        subset = [
            r for r in records if (r["source"] == "original-path-render") == (group == "controlled")
        ]
        for algorithm in ("det", "rec", "template_diagnostic_top"):
            counts = {}
            for row in subset:
                if algorithm == "template_diagnostic_top":
                    value = str(row["ranking"][0][1])
                else:
                    candidates = next(r for r in row["results"] if r["request_key"] == algorithm)[
                        "all_candidates"
                    ]
                    value = "|".join(c["text"] for c in candidates) or "missing"
                key = f"{row['truth']}->{value}"
                counts[key] = counts.get(key, 0) + 1
            confusion[group][algorithm] = counts
    (output / "summary.json").write_text(
        json.dumps(
            dict(
                count=len(records),
                confusion=confusion,
                controlled_min_margin=min(
                    r["margin"] for r in records if r["source"] == "original-path-render"
                ),
                mean_seconds=sum(r["seconds"] for r in records) / len(records),
            ),
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    with quiz_vision_bundle() as bundle:
        asyncio.run(run(Path(sys.argv[1]), bundle))
