"""MaaFramework CustomController backed by BCA's explicit CDP Target.

Install the optional lite dependency to import this module. The surrounding
application must keep the CDP asyncio loop alive while Maa callbacks run in
workers. On cancellation revoke bridge entry, join jobs, then drain providers.
"""

from __future__ import annotations

import asyncio

import numpy as np
from maa.controller import CustomController  # type: ignore[import-untyped]
from maa.library import Library  # type: ignore[import-untyped]
from numpy.typing import NDArray

from .bridge import BridgeError, CDPBridge


class MaaCDPController(CustomController):  # type: ignore[misc]
    """Initial CDP adapter: screenshot and single-click; unsupported calls fail."""

    def __init__(self, bridge: CDPBridge, *, raw_size: bool = True) -> None:
        self._bridge = bridge
        self._handle = None  # Also makes upstream __del__ safe on partial initialization.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise BridgeError("create native controller in a worker thread")
        super().__init__()
        if not self.set_screenshot_use_raw_size(raw_size):
            self.close()
            raise RuntimeError("Maa rejected screenshot size policy")

    def close(self) -> None:
        """Owner-worker only, after jobs stop. Never post/use this object afterward.

        v5.16.1 has no public close. Isolate its destructor's native release here,
        clear the handle to make later __del__ harmless, keep callbacks alive until
        destroy returns. The application must join this worker before providers.
        """
        handle = getattr(self, "_handle", None)
        if handle:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                raise BridgeError("destroy native controller in a worker thread")
            Library.framework().MaaControllerDestroy(handle)
            self._handle = None

    def connect(self) -> bool:
        return self._bridge.connected

    def connected(self) -> bool:
        return self._bridge.connected

    def request_uuid(self) -> str:
        return f"bca-cdp:{self._bridge.bound_page_id or 'unbound'}"

    def get_features(self) -> int:
        # Let Maa use click() directly, rather than synthesizing touch down/up.
        return 0

    def start_app(self, intent: str) -> bool:
        return False

    def stop_app(self, intent: str) -> bool:
        return False

    def screencap(self) -> NDArray[np.uint8]:
        try:
            return self._bridge.screencap()
        except Exception:
            # Empty image maps to failure without leaking exceptions through ctypes.
            return np.empty((0, 0, 3), dtype=np.uint8)

    def click(self, x: int, y: int) -> bool:
        return self._bridge.click(x, y)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int) -> bool:
        return False

    def touch_down(self, contact: int, x: int, y: int, pressure: int) -> bool:
        return False

    def touch_move(self, contact: int, x: int, y: int, pressure: int) -> bool:
        return False

    def touch_up(self, contact: int) -> bool:
        return False

    def click_key(self, keycode: int) -> bool:
        return False

    def input_text(self, text: str) -> bool:
        return False

    def key_down(self, keycode: int) -> bool:
        return False

    def key_up(self, keycode: int) -> bool:
        return False
