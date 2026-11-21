import json
from dataclasses import asdict

import pytest
from PIL import Image

from bca.plugin_sdk.assets import AssetStore
from bca.plugin_sdk.vision import MatchOptions, PixelRect, PreprocessMode, match_frame

from .conftest import FIXTURES, frame_of

DATA = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", DATA["cases"], ids=lambda c: c["name"])
def test_labeled_dataset(case):
    store = AssetStore(FIXTURES, profile=FIXTURES / case["profile"] if case["profile"] else None)
    try:
        template = store.load("ui.target")
        assert store.load("ui.target") is template
        templates = [template]
        if case["status"] == "ambiguous":
            templates.append(store.load("ui.rival"))
        roi = (
            PixelRect(**dict(zip(("x", "y", "width", "height"), case["roi"], strict=True)))
            if case["roi"]
            else None
        )
        with Image.open(FIXTURES / case["image"]) as image:
            frame = frame_of(image, format="JPEG" if case["group"] == "jpeg" else "PNG")
        before = template.image.tobytes()
        result = match_frame(
            frame,
            templates,
            options=MatchOptions(
                threshold=DATA["threshold"],
                mode=PreprocessMode(case["mode"]),
                scales=(tuple(case["scale"]),),
                roi=roi,
            ),
        )
        assert result.status.value == case["status"]
        actual = [group[0] for group in result.ambiguous] if result.ambiguous else result.matches
        # Match sorting is score-first; labels compare spatial sets, not uncertain score order.
        boxes = sorted([list(asdict(c.bbox).values()) for c in actual])
        assert boxes == sorted(case["bboxes"])
        for c in actual:
            assert c.center == (
                c.bbox.x + (c.bbox.width - 1) / 2,
                c.bbox.y + (c.bbox.height - 1) / 2,
            )
        assert template.image.tobytes() == before
        if case["group"] == "mask":
            assert template.mask[0].tolist() == DATA["mask_effective_first_row"]
    finally:
        store.close()
