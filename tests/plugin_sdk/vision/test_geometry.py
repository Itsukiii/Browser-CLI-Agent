import numpy as np
import pytest

from bca.core.protocol import Viewport
from bca.plugin_sdk.vision import MatchOptions, PixelRect, match_frame

from .conftest import frame_of


@pytest.mark.parametrize("dpr", [1, 1.5, 2])
def test_nonuniform_region_geometry(dpr, make_template):
    pixels = np.arange(60, dtype=np.uint8).reshape(4, 5, 3)
    template = make_template(pixels)
    image = np.full((40, 80, 3), 200, np.uint8)
    image[17:21, 31:36] = pixels
    viewport = Viewport(
        width=400,
        height=300,
        capture_x=13,
        capture_y=29,
        capture_width=160,
        capture_height=60,
        device_scale_factor=dpr,
        scroll_x=200,
        scroll_y=500,
    )
    frame = frame_of(image, viewport=viewport)
    result = match_frame(
        frame, [template], options=MatchOptions(roi=PixelRect(x=20, y=10, width=30, height=20))
    )
    assert result.matches[0].center == (33, 18.5)
    assert frame.pixel_to_css(*result.matches[0].center) == (79, 56.75)
