from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from bca.core.errors import ValidationError
from bca.core.protocol import ImageFormat
from bca.plugin_sdk.vision import VisionDecodeError, VisionInputError, decode_frame

from .conftest import frame_of


@pytest.mark.parametrize("format", ["PNG", "JPEG"])
@pytest.mark.parametrize("mode", ["RGB", "L"])
def test_formats(mode, format):
    frame = frame_of(Image.new(mode, (5, 3), 90 if mode == "L" else (80, 120, 160)), format=format)
    decoded = decode_frame(frame)
    assert decoded.frame is frame
    assert decoded.image.shape == (3, 5, 3)
    assert decoded.image.dtype == np.uint8 and decoded.image.flags.c_contiguous
    assert not decoded.image.flags.writeable
    expected = [90, 90, 90] if mode == "L" else [80, 120, 160]
    assert np.max(abs(decoded.image[0, 0].astype(int) - expected)) <= 1
    with pytest.raises(ValueError):
        decoded.image.setflags(write=True)
    with pytest.raises(ValueError):
        decoded.image[0, 0] = 0


@pytest.mark.parametrize(
    "alpha,expected", [(0, [0, 0, 0]), (128, [100, 50, 25]), (255, [200, 100, 50])]
)
def test_alpha_black_composite(alpha, expected):
    decoded = decode_frame(frame_of(Image.new("RGBA", (2, 1), (200, 100, 50, alpha))))
    assert decoded.image[0, 0].tolist() == expected


def test_la_and_palette():
    decoded = decode_frame(frame_of(Image.new("LA", (1, 1), (200, 128))))
    assert decoded.image[0, 0].tolist() == [100] * 3
    p = Image.new("P", (1, 1))
    p.putpalette([200, 100, 50] + [0] * 765)
    p.info["transparency"] = 128  # Palette index 128, index zero remains opaque.
    assert decode_frame(frame_of(p)).image[0, 0].tolist() == [200, 100, 50]


@pytest.mark.parametrize("kind", ["truncated", "crc", "dimensions", "pixels", "depth", "limit"])
def test_corrupt(kind):
    frame = frame_of(Image.new("RGB", (3, 2), "red"))
    if kind == "truncated":
        frame = replace(frame, data=frame.data[:-15])
    elif kind == "crc":
        data = bytearray(frame.data)
        data[29] ^= 1
        frame = replace(frame, data=bytes(data))
    elif kind == "dimensions":
        frame = replace(frame, width=4)
    elif kind == "pixels":
        data = bytearray(frame.data)
        data[45] ^= 255
        frame = replace(frame, data=bytes(data))
    elif kind == "depth":
        frame = frame_of(Image.new("I;16", (3, 2), 1000))
    else:
        frame = replace(frame, width=4097, height=4096)
    with pytest.raises(VisionDecodeError):
        decode_frame(frame)


def test_jpeg_truncated_and_invalid_protocol():
    frame = frame_of(Image.new("RGB", (8, 8), "red"), format="JPEG")
    with pytest.raises(VisionDecodeError):
        decode_frame(replace(frame, data=frame.data[:-20]))
    for kwargs in ({"data": b""}, {"width": True}, {"format": ImageFormat.PNG}):
        with pytest.raises(ValidationError):
            replace(frame, **kwargs)
    with pytest.raises(VisionInputError):
        decode_frame(None)


def test_exact_limit():
    frame = frame_of(Image.new("L", (4096, 4096), 0))
    assert decode_frame(frame).image.shape == (4096, 4096, 3)
