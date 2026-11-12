"""Asynchronous capability contracts; implementations are owned by Core."""

from abc import ABC, abstractmethod
from typing import ClassVar

from bca.core.protocol import Action, ActionResult, Frame


class Provider(ABC):
    capability: ClassVar[str]

    @property
    @abstractmethod
    def available(self) -> bool:
        """Fast local readiness check; false before start and after close."""

    @abstractmethod
    async def start(self) -> None:
        """Acquire resources. Repeated starts while ready must be harmless."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources, including partial startup. Must be idempotent."""


class CaptureProvider(Provider):
    capability = "capture"

    @abstractmethod
    async def capture(self, page_id: str) -> Frame:
        """Return an owned immutable frame or raise ProviderError."""


class InputProvider(Provider):
    capability = "input"

    @abstractmethod
    async def execute(self, action: Action) -> ActionResult:
        """Execute one action. Expected execution failures return a failed result."""
