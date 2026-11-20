"""Borrowed CaptureProvider view recording actual frames for BrowserFreshness."""

from bca.core.browser import BrowserSession
from bca.core.errors import CapabilityUnavailableError, LifecycleError, ValidationError
from bca.core.protocol import Frame
from bca.core.providers import CaptureProvider
from bca.core.runtime import BrowserFreshness


class FreshnessCaptureAdapter(CaptureProvider):
    def __init__(
        self, session: BrowserSession, raw_capture: CaptureProvider, policy: BrowserFreshness
    ) -> None:
        if isinstance(raw_capture, FreshnessCaptureAdapter):
            raise ValidationError("raw_capture cannot be another freshness adapter")
        self._session, self._raw, self._policy = session, raw_capture, policy
        self._started = self._closed = False

    @property
    def available(self) -> bool:
        return self._started and not self._closed and self._raw.available and self._session.is_ready

    async def start(self) -> None:
        if self._closed:
            raise LifecycleError("capture adapter is closed")
        if not self._raw.available or not self._session.is_ready:
            raise CapabilityUnavailableError("borrowed capture/session is not ready")
        self._started = True

    async def close(self) -> None:
        self._closed = True
        self._started = False

    async def capture(self, page_id: str) -> Frame:
        if not self.available:
            raise CapabilityUnavailableError("capture adapter is not ready")
        if page_id != self._session.page_id:
            raise ValidationError("capture page differs from current binding")
        return await self._policy.capture(self._raw)
