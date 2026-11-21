"""Defensive array boundaries and deterministic image-space transforms."""

import math
from pathlib import Path
from typing import cast

import cv2
import numpy as np
from numpy.typing import NDArray

from bca.core.protocol import Frame
from bca.plugin_sdk.assets import AssetSelection, LoadedTemplate

from .errors import VisionInputError
from .models import MAX_PIXELS, DecodedFrame, MatchOptions, PixelRect, PreprocessMode


def array(value: NDArray[np.uint8], shape: tuple[int, ...]) -> None:
    if (
        not isinstance(value, np.ndarray)
        or value.dtype != np.uint8
        or value.shape != shape
        or not value.flags.c_contiguous
        or value.flags.writeable
    ):
        raise VisionInputError("expected contiguous readonly uint8 pixels of declared shape")


def validate_template(template: LoadedTemplate) -> None:
    if not isinstance(template, LoadedTemplate):
        raise VisionInputError("expected LoadedTemplate")
    if (
        not isinstance(template.asset_id, str)
        or not template.asset_id
        or not isinstance(template.variant_id, str)
        or not template.variant_id
        or not isinstance(template.source, Path)
    ):
        raise VisionInputError("invalid template identity or source")
    if (
        type(template.width) is not int
        or type(template.height) is not int
        or min(template.width, template.height) < 1
        or template.width * template.height > MAX_PIXELS
    ):
        raise VisionInputError("invalid template dimensions")
    if (
        not isinstance(template.selection, AssetSelection)
        or template.selection.asset_id != template.asset_id
        or template.selection.variant_id != template.variant_id
        or template.source != template.selection.source
    ):
        raise VisionInputError("inconsistent template selection")
    array(template.image, (template.height, template.width, 3))
    if template.mask is not None:
        array(template.mask, (template.height, template.width))
        if not np.any(template.mask):
            raise VisionInputError("mask has no effective weight")


def prepare_frame(
    decoded: DecodedFrame, options: MatchOptions
) -> tuple[NDArray[np.uint8], PixelRect]:
    if not isinstance(decoded, DecodedFrame) or not isinstance(decoded.frame, Frame):
        raise VisionInputError("expected DecodedFrame")
    frame = decoded.frame
    if frame.width * frame.height > MAX_PIXELS:
        raise VisionInputError("frame exceeds pixel limit")
    array(decoded.image, (frame.height, frame.width, 3))
    roi = options.roi or PixelRect(x=0, y=0, width=frame.width, height=frame.height)
    if roi.x + roi.width > frame.width or roi.y + roi.height > frame.height:
        raise VisionInputError("roi exceeds Frame")
    image = decoded.image[roi.y : roi.y + roi.height, roi.x : roi.x + roi.width]
    if options.mode is PreprocessMode.GRAY:
        image = cast(NDArray[np.uint8], cv2.cvtColor(image, cv2.COLOR_RGB2GRAY))
    return np.ascontiguousarray(image), roi


def scaled_size(template: LoadedTemplate, scale: tuple[float, float]) -> tuple[int, int]:
    return (
        max(1, math.floor(template.width * scale[0] + 0.5)),
        max(1, math.floor(template.height * scale[1] + 0.5)),
    )


def prepare_template(
    template: LoadedTemplate, size: tuple[int, int], mode: PreprocessMode
) -> tuple[NDArray[np.uint8], NDArray[np.float32] | None]:
    image, mask = template.image, template.mask
    if size != (template.width, template.height):
        interpolation = (
            cv2.INTER_AREA
            if size[0] <= template.width and size[1] <= template.height
            else cv2.INTER_LINEAR
        )
        image = cast(NDArray[np.uint8], cv2.resize(image, size, interpolation=interpolation))
        if mask is not None:
            interpolated = cv2.resize(mask.astype(np.float32), size, interpolation=cv2.INTER_LINEAR)
            mask = np.floor(interpolated + 0.5).clip(0, 255).astype(np.uint8)
    if mode is PreprocessMode.GRAY:
        image = cast(NDArray[np.uint8], cv2.cvtColor(image, cv2.COLOR_RGB2GRAY))
    if mask is not None and not np.any(mask):
        raise VisionInputError("scaled mask has no effective weight")
    weights = None if mask is None else mask.astype(np.float32) / np.float32(255)
    return image, weights
