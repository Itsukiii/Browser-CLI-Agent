"""Synchronous Maa callbacks; mutable browser state belongs to one asyncio loop."""

from __future__ import annotations

import asyncio
import math
import threading
import time
from collections.abc import Callable, Coroutine
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from io import BytesIO
from typing import Any, TypeVar

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from bca.core.browser import BrowserCaptureProvider, BrowserInputProvider, BrowserSession
from bca.core.browser.geometry import Geometry, measure_geometry
from bca.core.protocol import Action, ActionStatus, ActionType, Frame, MouseButton

_T = TypeVar("_T")


class BridgeError(RuntimeError):
    """Rejected operation; never an authorization to retry input."""


@dataclass(frozen=True, eq=False)
class ObservationRef:
    """Opaque identity, issued by this bridge. A copy does not authorize input."""

    frame: Frame
    geometry: Geometry
    observed_at: float


class CDPBridge:
    """Borrow a fixed binding and started providers, exclusively used by this bridge.

    Construct on the owner loop. Native callbacks run elsewhere. Each successful
    capture replaces the one-shot observation. No DOM/semantic atomicity is claimed.
    A timeout or unconfirmed input permanently blocks this instance.
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
        require_authorization: bool = False,
    ) -> None:
        if asyncio.get_running_loop() is not loop:
            raise ValueError("construct bridge on its owner event loop")
        if any(not math.isfinite(v) or v <= 0 for v in (timeout, max_frame_age)):
            raise ValueError("timeout and max_frame_age must be finite and positive")
        if not session.is_ready:
            raise BridgeError("bind an explicit target before creating the bridge")
        self._loop, self._session = loop, session
        self._capture, self._input = capture, input_provider
        self._timeout, self._max_frame_age = timeout, max_frame_age
        self._binding = self._identity()
        self._lock = asyncio.Lock()
        self._stopped = threading.Event()
        self._blocked = threading.Event()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._last: ObservationRef | None = None
        self._authorized: ObservationRef | None = None
        self._require_authorization = require_authorization
        self._last_error: str | None = None
        self._outcome = "not_attempted"

    @property
    def connected(self) -> bool:
        return (
            not self._stopped.is_set()
            and not self._blocked.is_set()
            and self._session.is_ready
            and self._identity() == self._binding
            and self._capture.available
            and self._input.available
        )

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def input_outcome(self) -> str:
        """not_attempted, rejected, confirmed, or unknown; confirmed is not business success."""
        return self._outcome

    @property
    def bound_page_id(self) -> str | None:
        return self._binding[1]

    @property
    def observation(self) -> ObservationRef | None:
        """Read on owner loop after a completed capture job; not a semantic revision."""
        self._require_owner()
        return self._last if self.connected else None

    def invalidate(self) -> None:
        """Nonblocking stop signal from any thread. Await aclose before closing providers."""
        self._stopped.set()

    async def authorize(self, reference: ObservationRef) -> None:
        """Arm exactly this live observation for one native click, on owner loop.

        Use require_authorization=True for application commands. The application
        must validate its semantic revision before each call; this is not a DOM
        transaction. A new screenshot, any click attempt, or stop revokes it.
        """
        self._require_owner()
        async with self._lock:
            self._authorized = None
            self._check(reference)
            if reference is not self._last:
                raise BridgeError("observation is obsolete or belongs to another bridge")
            self._authorized = reference

    def _require_owner(self) -> None:
        if asyncio.get_running_loop() is not self._loop:
            raise BridgeError("operation requires browser owner loop")

    async def aclose(self) -> None:
        """Drain submitted coroutines (including cancellation cleanup), never native jobs.

        The caller must also join its native worker while this loop remains alive.
        Submissions not yet started see the stop flag and cannot access providers.
        """
        self._require_owner()
        self.invalidate()
        self._last = None
        self._authorized = None
        if self._tasks:
            drain = asyncio.gather(*tuple(self._tasks), return_exceptions=True)
            cancelled = False
            while not drain.done():
                try:
                    await asyncio.shield(drain)
                except asyncio.CancelledError:
                    cancelled = True
            drain.result()
            if cancelled:
                raise asyncio.CancelledError

    def _identity(self) -> tuple[object, str | None, str | None, int]:
        s = self._session
        return s.connection, s.page_id, s.session_id, s.generation

    def _check(self, saved: ObservationRef | None = None) -> None:
        if not self.connected:
            raise BridgeError("bridge stopped, blocked, or binding changed")
        if saved is not None and time.monotonic() - saved.observed_at > self._max_frame_age:
            raise BridgeError("screenshot expired")

    async def _serialized(self, factory: Callable[[], Coroutine[Any, Any, _T]]) -> _T:
        self._check()
        task = asyncio.current_task()
        assert task is not None
        self._tasks.add(task)
        try:
            async with self._lock:
                self._check()
                return await factory()
        finally:
            self._tasks.discard(task)

    def _call(self, factory: Callable[[], Coroutine[Any, Any, _T]]) -> _T:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is self._loop:
            raise BridgeError("Maa callback would block the browser event loop")
        if not self._loop.is_running():
            raise BridgeError("browser event loop is not running")
        self._check()
        coro = self._serialized(factory)
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        except BaseException:
            coro.close()
            raise
        try:
            return future.result(timeout=self._timeout)
        except FutureTimeoutError as exc:
            self._blocked.set()
            self._last_error = "CallbackTimeout"
            future.cancel()  # aclose still waits for the real coroutine's finally.
            raise BridgeError("CDP callback timed out; drain and retire bridge") from exc

    async def _capture_frame(self) -> NDArray[np.uint8]:
        self._last = None
        self._authorized = None
        self._check()
        page_id = self.bound_page_id
        assert page_id is not None
        before = await measure_geometry(self._session)
        self._check()
        started = time.monotonic()  # Includes capture latency in the freshness budget.
        frame = await self._capture.capture(page_id)
        self._check()
        after = await measure_geometry(self._session)
        self._check()
        if before != after or frame.page_id != page_id or frame.session_id != self._binding[2]:
            raise BridgeError("CDP page changed during screenshot")
        bgr = await asyncio.to_thread(self._decode, frame)
        saved = ObservationRef(frame, after, started)
        self._check(saved)
        self._last = saved
        self._last_error = None
        return bgr

    @staticmethod
    def _decode(frame: Frame) -> NDArray[np.uint8]:
        with Image.open(BytesIO(frame.data)) as image:
            bgr = np.asarray(image.convert("RGB"), dtype=np.uint8)[:, :, ::-1].copy()
        if bgr.shape[:2] != (frame.height, frame.width):
            raise BridgeError("decoded dimensions disagree with Frame")
        return bgr

    def screencap(self) -> NDArray[np.uint8]:
        try:
            return self._call(self._capture_frame)
        except Exception as exc:
            if self._last_error != "CallbackTimeout":
                self._last_error = str(exc) if isinstance(exc, BridgeError) else type(exc).__name__
            raise

    async def _click_frame(self, x: int, y: int) -> bool:
        saved, self._last = self._last, None
        authorized, self._authorized = self._authorized, None
        self._outcome = "rejected"
        if saved is None:
            raise BridgeError("NoFreshFrame")
        if self._require_authorization and authorized is not saved:
            raise BridgeError("observation is not explicitly authorized")
        if type(x) is not int or type(y) is not int:
            raise BridgeError("InvalidCoordinates")
        self._check(saved)
        geometry = await measure_geometry(self._session)
        self._check(saved)  # Identity, stop, and age may change during the await.
        if geometry != saved.geometry:
            raise BridgeError("browser document/geometry changed since screenshot")
        css_x, css_y = saved.frame.pixel_to_css(x, y)
        action = Action(
            page_id=saved.frame.page_id,
            type=ActionType.MOUSE_CLICK,
            x=css_x,
            y=css_y,
            button=MouseButton.LEFT,
        )
        self._outcome = "unknown"
        try:
            result = await self._input.execute(action)
            if result.status is not ActionStatus.SUCCEEDED or result.action_id != action.action_id:
                raise BridgeError("browser did not confirm matching click")
            self._check()
        except BaseException:
            self._blocked.set()
            raise
        self._outcome = "confirmed"
        self._last_error = None
        return True

    def click(self, x: int, y: int) -> bool:
        try:
            return self._call(lambda: self._click_frame(x, y))
        except Exception as exc:
            if self._last_error != "CallbackTimeout":
                self._last_error = str(exc) if isinstance(exc, BridgeError) else type(exc).__name__
            return False


async def run_native[T](bridge: CDPBridge, operation: Callable[[], T]) -> T:
    """Own one native worker until it exits, including repeated caller cancellation.

    operation must destroy its Maa objects in finally. No force-kill or automatic
    replay: cancellation revokes bridge entry, then waits with the CDP loop alive.
    """
    worker = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        bridge.invalidate()
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not worker.cancelled():
            worker.exception()
        raise
