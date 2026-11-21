import numpy as np
import pytest

from bca.plugin_sdk.vision import PreprocessMode, VisionInputError
from bca.plugin_sdk.vision.preprocess import prepare_template, scaled_size


def test_scale_rounding_mask_and_immutability(make_template):
    pixels = np.arange(45, dtype=np.uint8).reshape(3, 5, 3)
    mask = np.array([[0, 64, 128, 255, 255]] * 3, np.uint8)
    template = make_template(pixels, mask)
    assert scaled_size(template, (0.5, 1.5)) == (3, 5)
    rgb, weights = prepare_template(template, (10, 6), PreprocessMode.RGB)
    assert rgb.shape == (6, 10, 3) and weights.shape == (6, 10)
    # Half-pixel linear interpolation: 0,16,48,80,112,160,223,255,255,255.
    np.testing.assert_allclose(
        weights[0] * 255, [0, 16, 48, 80, 112, 160, 223, 255, 255, 255], atol=1e-5
    )
    np.testing.assert_array_equal(template.image, pixels)
    np.testing.assert_array_equal(template.mask, mask)
    gray, _ = prepare_template(template, (5, 3), PreprocessMode.GRAY)
    # RGB [0,1,2] -> OpenCV fixed BT.601 rounding yields 1.
    assert gray[0, 0] == 1


def test_scaled_empty_mask(make_template):
    pixels = np.zeros((8, 8, 3), np.uint8)
    mask = np.zeros((8, 8), np.uint8)
    mask[0, 0] = 1
    template = make_template(pixels, mask)
    with pytest.raises(VisionInputError, match="scaled mask"):
        prepare_template(template, (2, 2), PreprocessMode.RGB)
