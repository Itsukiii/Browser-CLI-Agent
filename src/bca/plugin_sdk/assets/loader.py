"""Static PNG/JPEG decoding to immutable RGB bytes-backed NumPy arrays."""

import warnings
from io import BytesIO

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from .errors import AssetDecodeError, AssetValidationError
from .models import AssetSelection, LoadedTemplate

MAX_PIXELS = 16_777_216
MODES = {"RGB", "RGBA", "L", "LA", "P"}


def decode(data: bytes, *, mask: bool = False) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as probe:
                if probe.format not in ("PNG", "JPEG"):
                    raise AssetDecodeError("image: only PNG/JPEG supported")
                if probe.width <= 0 or probe.height <= 0 or probe.width * probe.height > MAX_PIXELS:
                    raise AssetValidationError("image: pixel limit exceeded")
                if getattr(probe, "n_frames", 1) != 1:
                    raise AssetDecodeError("image: animated or multi-frame input not supported")
                if mask and probe.mode != "L":
                    raise AssetValidationError("mask: expected 8-bit grayscale L")
                if probe.mode not in MODES:
                    raise AssetDecodeError("image: unsupported color mode")
                # Integrity checks precede reopening for full pixel decompression.
                probe.verify()
            with Image.open(BytesIO(data)) as image:
                image.load()
                return image.copy()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise AssetValidationError("image: pixel limit exceeded") from exc
    except (OSError, ValueError, SyntaxError, EOFError) as exc:
        raise AssetDecodeError("image: invalid or truncated data") from exc


def readonly(data: bytes, shape: tuple[int, ...]) -> NDArray[np.uint8]:
    return np.frombuffer(data, dtype=np.uint8).reshape(shape)


def load_template(
    selection: AssetSelection, image_data: bytes, mask_data: bytes | None
) -> LoadedTemplate:
    with decode(image_data) as image:
        width, height = image.size
        if selection.size is not None and selection.size != (width, height):
            raise AssetValidationError("image: declared size mismatch")
        alpha: NDArray[np.uint8] | None = None
        if image.mode in ("RGBA", "LA") or "transparency" in image.info:
            with image.convert("RGBA") as rgba, rgba.getchannel("A") as channel:
                alpha = readonly(channel.tobytes(), (height, width))
                with rgba.convert("RGB") as rgb:
                    pixels = readonly(rgb.tobytes(), (height, width, 3))
        else:
            with image.convert("RGB") as rgb:
                pixels = readonly(rgb.tobytes(), (height, width, 3))
    weights = alpha
    if mask_data is not None:
        with decode(mask_data, mask=True) as external:
            if external.size != (width, height):
                raise AssetValidationError("mask: image size mismatch")
            external_array = readonly(external.tobytes(), (height, width))
        if alpha is not None:
            combined = (alpha.astype(np.uint16) * external_array.astype(np.uint16) + 127) // 255
            weights = readonly(combined.astype(np.uint8).tobytes(), (height, width))
        else:
            weights = external_array
    if weights is not None:
        if not np.any(weights):
            raise AssetValidationError("mask: all weights are zero")
        if mask_data is None and np.all(weights == 255):
            weights = None
    return LoadedTemplate(
        asset_id=selection.asset_id,
        variant_id=selection.variant_id,
        image=pixels,
        mask=weights,
        width=width,
        height=height,
        source=selection.source,
        selection=selection,
    )
