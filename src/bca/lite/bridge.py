"""Fail-closed, synchronous Maa callbacks over an async, explicitly bound CDP page.

The owner asyncio loop must keep running on a *different* thread from the
MaaFramework callback. The application owns session/providers and their close.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Callable, Coroutine, TypeVar

import numpy as np
from PIL import Image

from bca.core.browser import BrowserCaptureProvider, BrowserInputProvider, BrowserSession
from bca.core.browser.geometry import Geometry, measure_geometry
from bca.core.protocol import Action, ActionStatus, ActionType, Frame, MouseButton

_T = TypeVar("_T")
logger = logging.getLogger(__name__)


class BridgeError(RuntimeError):
    """A browser callback was rejected; no automatic retry is permitted."""


@dataclass(frozen=True)
class _Captured:
    frame: Frame
    geometry: Geometry
    identity: tuple[object, ...]
    monotonic_time: float


class CDPBridge:
    """Borrow an already connected/bound BrowserSession and started providers.

    One bridge is tied to a single explicit CDP binding. Calls are serialized
    between worker threads. Maa must consume the original image resolution;
    Maa's own controller scaling converts its recognition positions back to
    the raw image coordinate system before invoking click.

    In-page DOM changes without geometry/URL changes are not detectable from
    this callback API: the application must additionally reobserve before any
    high-risk or delayed business action.
    """

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        session: BrowserSession,
        capture: BrowserCaptureProvider,
        input_provider: BrowserInputProvider,
        timeout: float = 10.0,
        max_frame_age: float = 2.0,
    ) -> None:
        if timeout <= 0 or max_frame_age <= 0:
            raise ValueError("timeout and max_frame_age must be positive")
        self._loop = loop
        self._session = session
        self._capture = capture
        self._input = input_provider
        self._timeout = timeout
        self._max_frame_age = max_frame_age
        self._lock = threading.Lock()
        self._last: _Captured | None = None
        self._closed = False
        self._blocked = False
        self._last_error: str | None = None

    @property
    def connected(self) -> bool:
        return (not self._closed and not self._blocked and self._session.is_ready
                and self._capture.available and self._input.available)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def bound_page_id(self) -> str | None:
        return self._session.page_id

    def invalidate(self) -> None:
        """Stop accepting callbacks before the application closes the providers."""
        with self._lock:
            self._closed = True
            self._last = None

    def _identity(self) -> tuple[object, ...]:
        session = self._session
        return (session.connection, session.page_id, session.session_id, session.generation)

    def _call(self, factory: Callable[[], Coroutine[Any, Any, _T]]) -> _T:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is self._loop:
            raise BridgeError("Maa callback would block the browser event loop")
        if not self._loop.is_running() or self._closed or self._blocked:
            raise BridgeError("browser bridge is stopped or blocked")
        future = asyncio.run_coroutine_threadsafe(factory(), self._loop)
        try:
            return future.result(timeout=self._timeout)
        except FutureTimeoutError as exc:
            # The native callback already lost certainty about a dispatched
            # operation; never issue a second input or retry it implicitly.
            self._blocked = True
            future.cancel()
            raise BridgeError("CDP callback timed out; recreate bridge before retrying") from exc

    async def _capture_frame(self) -> _Captured:
        if not self.connected:
            raise BridgeError("bound page or providers are not ready")
        identity = self._identity()
        page_id = self._session.page_id
        if page_id is None:
            raise BridgeError("no explicitly bound page")
        before = await measure_geometry(self._session)
        frame = await self._capture.capture(page_id)
        after = await measure_geometry(self._session)
        if (before != after or identity != self._identity()
                or frame.page_id != page_id or frame.session_id != self._session.session_id):
            raise BridgeError("CDP page changed during screenshot")
        return _Captured(frame, after, identity, time.monotonic())

    def screencap(self) -> np.ndarray:
        """Return full-resolution BGR pixels as required by Maa CustomController."""
        with self._lock:
            self._last = None
            try:
                captured = self._call(self._capture_frame)
                with Image.open(BytesIO(captured.frame.data)) as image:
                    bgr = np.asarray(image.convert("RGB"), dtype=np.uint8)[:, :, ::-1].copy()
                if bgr.shape[:2] != (captured.frame.height, captured.frame.width):
                    raise BridgeError("decoded dimensions disagree with Frame")
                self._last = captured
                self._last_error = None
                return bgr
            except Exception as exc:
                self._last_error = type(exc).__name__
                logger.warning("Maa CDP screenshot failed: %s", type(exc).__name__)
                raise

    async def _click_frame(self, saved: _Captured, x: int, y: int) -> bool:
        if not self.connected or saved.identity != self._identity():
            raise BridgeError("stale or disconnected CDP binding")
        if time.monotonic() - saved.monotonic_time > self._max_frame_age:
            raise BridgeError("screenshot is too old for input")
        if await measure_geometry(self._session) != saved.geometry:
            raise BridgeError("browser document/geometry changed since screenshot")
        css_x, css_y = saved.frame.pixel_to_css(x, y)
        result = await self._input.execute(
            Action(
                page_id=saved.frame.page_id,
                type=ActionType.MOUSE_CLICK,
                x=css_x,
                y=css_y,
                button=MouseButton.LEFT,
            )
        )
        if result.status is not ActionStatus.SUCCEEDED:
            raise BridgeError("browser did not confirm click")
        return True

    def click(self, x: int, y: int) -> bool:
        """Use ONLY coordinates from the last valid, fresh screencap callback."""
        with self._lock:
            saved = self._last
            self._last = None  # One screenshot authorizes at most one click.
            if saved is None:
                self._last_error = "NoFreshFrame"
                return False
            if type(x) is not int or type(y) is not int:
                self._last_error = "InvalidCoordinates"
                return False
            try:
                ok = self._call(lambda: self._click_frame(saved, x, y))
                self._last_error = None
                return ok
            except Exception as exc:
                self._last_error = type(exc).__name__
                logger.warning("Maa CDP click rejected: %s", type(exc).__name__)
                return False
