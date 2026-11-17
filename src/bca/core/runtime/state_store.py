"""Latest-state storage for one observation channel on a single asyncio loop."""

import asyncio
from dataclasses import dataclass

from bca.core.errors import LifecycleError, ValidationError
from bca.core.protocol import PageState


class StateStoreClosedError(LifecycleError):
    code = "runtime.state_store_closed"


@dataclass(frozen=True, kw_only=True)
class StateSnapshot:
    version: int
    state: PageState

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version < 1:
            raise ValidationError("snapshot version must be a positive integer")
        if not isinstance(self.state, PageState):
            raise ValidationError("snapshot state must be PageState")


class StateStore:
    """Structurally implements StateSink; accepted payloads must remain read-only."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._snapshot: StateSnapshot | None = None
        self._closed = False

    @property
    def version(self) -> int:
        return self._snapshot.version if self._snapshot else 0

    @property
    def closed(self) -> bool:
        return self._closed

    def snapshot(self) -> StateSnapshot | None:
        return self._snapshot

    async def publish(self, state: PageState) -> None:
        if not isinstance(state, PageState):
            raise ValidationError("state must be PageState")
        async with self._condition:
            if self._closed:
                raise StateStoreClosedError("state store is closed")
            self._snapshot = StateSnapshot(version=self.version + 1, state=state)
            self._condition.notify_all()

    async def wait_for_update(self, after_version: int) -> StateSnapshot | None:
        if type(after_version) is not int or after_version < 0:
            raise ValidationError("after_version must be a nonnegative integer")
        async with self._condition:
            await self._condition.wait_for(lambda: self.version > after_version or self._closed)
            return self._snapshot if self.version > after_version else None

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            self._condition.notify_all()
