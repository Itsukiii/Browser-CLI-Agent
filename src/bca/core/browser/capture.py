"""On-demand PNG capture, with measured CSS geometry and pixel-aligned crops."""

import asyncio
import base64
import binascii
import logging
import math
import struct
from datetime import UTC, datetime
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from bca.core.errors import CapabilityUnavailableError, LifecycleError, ValidationError
from bca.core.protocol import Frame, ImageFormat, Viewport
from bca.core.protocol.validation import number, positive, token
from bca.core.providers import CaptureProvider

from .errors import BrowserError, CDPTimeoutError, TargetLostError
from .geometry import Geometry, GeometryError, measure_geometry
from .session import BrowserSession

logger = logging.getLogger(__name__)


class CaptureError(BrowserError):
    code = "browser.capture"


_MAX_PIXELS = 16_000_000
_MAX_BYTES = 12_000_000


def _decode_crop(
    encoded: str, geometry: Geometry, region: tuple[float, float, float, float] | None
) -> tuple[bytes, int, int, Viewport]:
    try:
        if len(encoded) > (_MAX_BYTES + 2) // 3 * 4:
            raise CaptureError("screenshot exceeds encoded byte limit")
        data = base64.b64decode(encoded, validate=True)
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise CaptureError("expected a PNG screenshot")
        if len(data) < 33 or data[12:16] != b"IHDR":
            raise CaptureError("PNG header is incomplete")
        declared_width, declared_height = struct.unpack(">II", data[16:24])
        if (
            not declared_width
            or not declared_height
            or declared_width * declared_height > _MAX_PIXELS
        ):
            raise CaptureError("screenshot dimensions exceed pixel limit")
        with Image.open(BytesIO(data), formats=["PNG"]) as check:
            width, height = check.size
            if width <= 0 or height <= 0 or width * height > _MAX_PIXELS:
                raise CaptureError("screenshot dimensions exceed pixel limit")
            if getattr(check, "n_frames", 1) != 1:
                raise CaptureError("animated screenshots are unsupported")
            check.verify()  # PNG structure and CRC, not just IHDR/signature.
        with Image.open(BytesIO(data), formats=["PNG"]) as pixels:
            pixels.load()  # Check compressed data really decodes to the declared size.
            if pixels.size != (width, height):
                raise CaptureError("decoded PNG dimensions changed")
            sw, sh = geometry.surface_size
            # Native surface includes scrollbars. Keep only complete content pixels.
            max_right = min(width, math.floor(geometry.width * width / sw + 1e-9))
            max_bottom = min(height, math.floor(geometry.height * height / sh + 1e-9))
            left, top, right, bottom = 0, 0, max_right, max_bottom
            if region is not None:
                x, y, w, h = region
                left = max(0, math.floor(x * width / sw))
                top = max(0, math.floor(y * height / sh))
                right = min(max_right, math.ceil((x + w) * width / sw))
                bottom = min(max_bottom, math.ceil((y + h) * height / sh))
            if right <= left or bottom <= top:
                raise CaptureError("capture region contains no complete content pixel")
            if (left, top, right, bottom) != (0, 0, width, height):
                with pixels.crop((left, top, right, bottom)) as cropped:
                    output = BytesIO()
                    cropped.save(output, format="PNG")
                    data = output.getvalue()
            # Derive coverage from the raster; never multiply CSS coordinates by DPR.
            x0, y0 = left * sw / width, top * sh / height
            x1, y1 = (
                min(geometry.width, right * sw / width),
                min(geometry.height, bottom * sh / height),
            )
            viewport = Viewport(
                width=geometry.width,
                height=geometry.height,
                capture_x=x0,
                capture_y=y0,
                capture_width=x1 - x0,
                capture_height=y1 - y0,
                device_scale_factor=geometry.dpr,
                scroll_x=geometry.scroll_x,
                scroll_y=geometry.scroll_y,
            )
            return data, right - left, bottom - top, viewport
    except (
        ValueError,
        OSError,
        SyntaxError,
        binascii.Error,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as exc:
        raise CaptureError("invalid or incomplete PNG screenshot") from exc


class BrowserCaptureProvider(CaptureProvider):
    """Borrows a session; close invalidates in-flight capture but never closes the session."""

    def __init__(self, session: BrowserSession, *, timeout: float = 10.0) -> None:
        positive(timeout, "timeout")
        self._session = session
        self._timeout = timeout
        self._started = False
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self._started and not self._closed and self._session.is_ready

    async def start(self) -> None:
        if self._closed:
            raise LifecycleError("capture provider is closed")
        if not self._session.is_ready:
            raise CapabilityUnavailableError("bind a page before starting capture")
        self._started = True

    async def close(self) -> None:
        self._closed = True
        self._started = False

    async def capture(self, page_id: str) -> Frame:
        return await self._capture(page_id, None)

    async def capture_region(
        self, page_id: str, *, x: float, y: float, width: float, height: float
    ) -> Frame:
        number(x, "x", minimum=0)
        number(y, "y", minimum=0)
        positive(width, "width")
        positive(height, "height")
        return await self._capture(page_id, (x, y, width, height))

    async def _measure(self) -> Geometry:
        try:
            return await measure_geometry(self._session)
        except GeometryError as exc:
            raise CaptureError(str(exc)) from exc

    async def _capture(
        self, page_id: str, region: tuple[float, float, float, float] | None
    ) -> Frame:
        token(page_id, "page_id")
        if not self.available:
            raise CapabilityUnavailableError("capture provider is not ready")
        session = self._session
        if page_id != session.page_id:
            raise ValidationError("page_id must match the explicitly bound target")
        identity = (session.connection, session.page_id, session.session_id, session.generation)

        def check() -> None:
            if not self.available or identity != (
                session.connection,
                session.page_id,
                session.session_id,
                session.generation,
            ):
                raise TargetLostError("capture belongs to an unavailable or obsolete binding")

        try:
            async with asyncio.timeout(self._timeout):
                async with self._lock:
                    check()
                    before = await self._measure()
                    check()
                    if region is not None:
                        x, y, w, h = region
                        if x + w > before.width or y + h > before.height:
                            raise ValidationError("capture region exceeds the visible viewport")
                    # No CDP clip: avoid transient viewport emulation/resize during capture.
                    response = await session.send(
                        "Page.captureScreenshot",
                        {
                            "format": "png",
                            "fromSurface": True,
                            "captureBeyondViewport": False,
                        },
                    )
                    captured_at = datetime.now(UTC)
                    check()
                    encoded = response.get("data")
                    if not isinstance(encoded, str):
                        raise CaptureError("screenshot response has no encoded data")
                    data, width, height, viewport = await asyncio.to_thread(
                        _decode_crop, encoded, before, region
                    )
                    check()
                    after = await self._measure()
                    check()
                    if before != after:
                        raise CaptureError("document or viewport changed during screenshot")
                    return Frame(
                        width=width,
                        height=height,
                        data=data,
                        format=ImageFormat.PNG,
                        viewport=viewport,
                        page_id=page_id,
                        session_id=identity[2],
                        captured_at=captured_at,
                    )
        except TimeoutError as exc:
            raise CDPTimeoutError("capture exceeded its total timeout") from exc
