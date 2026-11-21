from dataclasses import replace

import numpy as np
import pytest

from bca.plugin_sdk.vision import (
    MatchOptions,
    PixelRect,
    VisionInputError,
    decode_frame,
    match_frame,
    match_templates,
)

from .conftest import frame_of


@pytest.mark.parametrize(
    "kwargs",
    [
        {"threshold": True},
        {"threshold": -1},
        {"threshold": float("nan")},
        {"threshold": float("inf")},
        {"threshold": 1.1},
        {"nms_iou": -1},
        {"ambiguity_margin": 2},
        {"mode": "rgb"},
        {"roi": (1, 2, 3, 4)},
        {"scales": []},
        {"scales": ()},
        {"scales": ((True, 1),)},
        {"scales": ((0.2, 1),)},
        {"scales": ((1, 5),)},
        {"scales": ((1, 1),) * 17},
        {"scales": ([1, 1],)},
        {"max_results": False},
        {"max_results": 0},
        {"max_results": 4097},
        {"max_proposals_per_variant": 1.5},
    ],
)
def test_options(kwargs):
    with pytest.raises(VisionInputError):
        MatchOptions(**kwargs)


@pytest.mark.parametrize(
    "field,value", [("x", -1), ("y", True), ("width", 0), ("height", 1.1), ("x", "1")]
)
def test_rect(field, value):
    kwargs = dict(x=0, y=0, width=1, height=1)
    kwargs[field] = value
    with pytest.raises(VisionInputError):
        PixelRect(**kwargs)


def test_boundaries(make_template):
    template = make_template(np.zeros((3, 4, 3), np.uint8))
    frame = frame_of(np.zeros((10, 12, 3), np.uint8))
    decoded = decode_frame(frame)
    for bad_id in ([], "", None):
        with pytest.raises(VisionInputError):
            match_templates(decoded, [replace(template, asset_id=bad_id)])
    with pytest.raises(VisionInputError):
        MatchOptions(threshold=10**500)
    for templates in ([], [object()], [template, template]):
        with pytest.raises(VisionInputError):
            match_templates(decoded, templates)
    for changed in (
        replace(template, image=template.image.copy()),
        replace(template, width=1),
        replace(template, mask=np.zeros((3, 4), np.uint8)),
        replace(template, asset_id="other"),
    ):
        with pytest.raises(VisionInputError):
            match_templates(decoded, [changed])
    with pytest.raises(VisionInputError):
        match_frame(
            frame, [template], options=MatchOptions(roi=PixelRect(x=10, y=0, width=3, height=3))
        )
    with pytest.raises(VisionInputError):
        match_templates(replace(decoded, image=decoded.image.copy()), [template])
