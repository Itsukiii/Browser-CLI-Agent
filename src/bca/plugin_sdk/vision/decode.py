"""Strict container/pixel validation followed by OpenCV RGB decoding."""

import warnings
from io import BytesIO

import cv2
import numpy as np
from PIL import Image

from bca.core.protocol import Frame, ImageFormat

from .errors import VisionDecodeError, VisionInputError
from .models import MAX_PIXELS, DecodedFrame


def decode_frame(frame: Frame) -> DecodedFrame:
    if not isinstance(frame, Frame):
        raise VisionInputError("expected a Protocol Frame")
    if frame.width * frame.height > MAX_PIXELS or len(frame.data) > 128 * 1024 * 1024:
        raise VisionDecodeError("frame exceeds decode limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(frame.data)) as probe:
                expected = "PNG" if frame.format is ImageFormat.PNG else "JPEG"
                if probe.format != expected or probe.size != (frame.width, frame.height):
                    raise VisionDecodeError("encoding or dimensions disagree with Frame")
                if probe.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                    raise VisionDecodeError("unsupported pixel depth or mode")
                if getattr(probe, "n_frames", 1) != 1:
                    raise VisionDecodeError("animated frames are unsupported")
                probe.verify()
            # verify() alone does not decompress JPEG/PNG pixel streams.
            with Image.open(BytesIO(frame.data)) as complete:
                complete.load()
            pixels = cv2.imdecode(np.frombuffer(frame.data, np.uint8), cv2.IMREAD_UNCHANGED)
            if pixels is None or pixels.dtype != np.uint8:
                raise VisionDecodeError("invalid decoded pixels")
            if pixels.ndim == 2:
                rgb = cv2.cvtColor(pixels, cv2.COLOR_GRAY2RGB)
            elif pixels.ndim == 3 and pixels.shape[2] == 3:
                rgb = cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB)
            elif pixels.ndim == 3 and pixels.shape[2] == 4:
                rgba = cv2.cvtColor(pixels, cv2.COLOR_BGRA2RGBA).astype(np.uint16)
                rgb = ((rgba[:, :, :3] * rgba[:, :, 3:] + 127) // 255).astype(np.uint8)
            else:
                raise VisionDecodeError("unsupported channel count")
            if rgb.shape != (frame.height, frame.width, 3):
                raise VisionDecodeError("decoded dimensions disagree with Frame")
            readonly = np.frombuffer(rgb.tobytes(), dtype=np.uint8).reshape(rgb.shape)
            return DecodedFrame(frame=frame, image=readonly)
    except VisionDecodeError:
        raise
    except (
        OSError,
        ValueError,
        SyntaxError,
        EOFError,
        cv2.error,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as exc:
        raise VisionDecodeError("frame integrity or decode failed") from exc
