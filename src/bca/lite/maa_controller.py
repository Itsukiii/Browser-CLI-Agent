"""MaaFramework CustomController backed by BCA's explicit CDP Target.

Install the optional lite dependency to import this module. The surrounding
application must keep the CDP asyncio loop alive while Maa callbacks run in
workers, and close Maa jobs before invalidating the bridge.
"""

from __future__ import annotations

import numpy as np
from maa.controller import CustomController

from .bridge import CDPBridge


class MaaCDPController(CustomController):
    """Initial CDP adapter: screenshot and single-click; unsupported calls fail."""

    def __init__(self, bridge: CDPBridge) -> None:
        self._bridge = bridge
        super().__init__()

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

    def screencap(self) -> np.ndarray:
        return self._bridge.screencap()

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
