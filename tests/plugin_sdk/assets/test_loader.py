import json
from dataclasses import FrozenInstanceError

import numpy as np
import pytest
from PIL import Image

from bca.plugin_sdk.assets import AssetDecodeError, AssetStore, AssetValidationError


def load(root, manifest, path, **fields):
    manifest({"v": {"path": path, **fields}}, default="v")
    return AssetStore(root).load("ui.confirm")


@pytest.mark.parametrize(
    "path,key,mask_key",
    [
        ("rgb.png", "rgb", None),
        ("dark.png", "dark", None),
        ("rgba.png", "rgb", "alpha"),
        ("opaque.png", "rgb", None),
        ("l.png", "gray", None),
        ("la.png", "gray", "la_mask"),
        ("palette.png", "rgb", "alpha"),
    ],
)
def test_exact_pixels_and_modes(assets_root, manifest, path, key, mask_key):
    expected = json.loads((assets_root / "expected.json").read_text())
    value = load(assets_root, manifest, path)
    assert value.image.tolist() == expected[key]
    assert value.image.dtype == np.uint8 and value.image.flags.c_contiguous
    assert value.image.shape == (value.height, value.width, 3) == (1, 2, 3)
    if mask_key is None:
        assert value.mask is None
    else:
        assert value.mask.tolist() == expected[mask_key]
        assert value.mask.dtype == np.uint8 and value.mask.flags.c_contiguous


def test_jpeg_and_mask_weights(assets_root, manifest):
    jpeg = load(assets_root, manifest, "rgb.jpg")
    # JPEG is lossy: fixed source RGB with explicit one-level codec tolerance.
    assert np.max(np.abs(jpeg.image.astype(int) - [80, 120, 160])) <= 1
    expected = json.loads((assets_root / "expected.json").read_text())
    combined = load(assets_root, manifest, "rgba.png", mask="mask.png")
    assert combined.mask.tolist() == expected["combined"] == [[64, 64]]
    external = load(assets_root, manifest, "rgb.png", mask="mask.png")
    assert external.mask.tolist() == [[128, 64]]
    white = load(assets_root, manifest, "rgb.png", mask="white.png")
    assert white.mask.tolist() == [[255, 255]]  # explicit masks retained


def test_bytes_backing_cannot_be_made_writable(assets_root, manifest):
    value = load(assets_root, manifest, "rgba.png")
    for array in (value.image, value.mask):
        with pytest.raises(ValueError):
            array.flat[0] = 0
        with pytest.raises(ValueError):
            array.setflags(write=True)
        base = array
        while isinstance(base, np.ndarray):
            with pytest.raises(ValueError):
                base.setflags(write=True)
            base = base.base
        assert isinstance(base, bytes)
        assert memoryview(array).readonly
        copy = array.copy()
        copy.flat[0] = 99
        assert array.flat[0] != 99
    with pytest.raises(FrozenInstanceError):
        value.width = 999


@pytest.mark.parametrize("fields", [{"size": [3, 1]}, {"mask": "zero.png"}, {"mask": "rgb.png"}])
def test_invalid_size_mask(assets_root, manifest, fields):
    with pytest.raises(AssetValidationError):
        load(assets_root, manifest, "rgba.png", **fields)


def test_mask_dimensions_and_all_zero_alpha(assets_root, manifest):
    with Image.new("L", (1, 1), 255) as image:
        image.save(assets_root / "small.png")
    with pytest.raises(AssetValidationError):
        load(assets_root, manifest, "rgb.png", mask="small.png")
    with Image.new("RGBA", (1, 1), (1, 2, 3, 0)) as image:
        image.save(assets_root / "transparent.png")
    with pytest.raises(AssetValidationError):
        load(assets_root, manifest, "transparent.png")


@pytest.mark.parametrize(
    "kind",
    [
        "garbage",
        "empty",
        "truncated_png",
        "truncated_jpeg",
        "crc",
        "gif",
        "cmyk",
        "integer",
        "animation",
    ],
)
def test_reject_corrupt_or_unsupported_input(assets_root, manifest, kind):
    path = assets_root / "bad.image"
    if kind in ("garbage", "empty"):
        path.write_bytes(b"not an image" if kind == "garbage" else b"")
    elif kind in ("truncated_png", "crc"):
        data = bytearray((assets_root / "rgb.png").read_bytes())
        if kind == "crc":
            data[45] ^= 0xFF
        else:
            data = data[:-18]
        path.write_bytes(data)
    elif kind == "truncated_jpeg":
        path.write_bytes((assets_root / "rgb.jpg").read_bytes()[:-20])
    elif kind == "animation":
        with Image.new("RGB", (2, 1), "red") as first, Image.new("RGB", (2, 1), "blue") as second:
            first.save(path, format="PNG", save_all=True, append_images=[second], duration=100)
    else:
        mode, fmt = {"gif": ("P", "GIF"), "cmyk": ("CMYK", "JPEG"), "integer": ("I;16", "PNG")}[
            kind
        ]
        with Image.new(mode, (2, 1)) as image:
            image.save(path, format=fmt)
    with pytest.raises(AssetDecodeError):
        load(assets_root, manifest, path.name)


def test_pixel_limit_checked_before_decompression(assets_root, manifest, monkeypatch):
    from bca.plugin_sdk.assets import loader

    monkeypatch.setattr(loader, "MAX_PIXELS", 1)
    with pytest.raises(AssetValidationError, match="pixel limit"):
        load(assets_root, manifest, "rgb.png")
