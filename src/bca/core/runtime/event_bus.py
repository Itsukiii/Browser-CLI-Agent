"""Bounded, atomic fan-out with membership selected at commit, on one asyncio loop."""

import asyncio
from collections import deque

from bca.core.errors import LifecycleError, ValidationError
from bca.core.protocol import Event


class EventBusClosedError(LifecycleError):
    code = "runtime.event_bus_closed"


class EventSubscription:
    """Created by EventBus.subscribe; explicit close discards pending notifications."""

    def __init__(self, bus: "EventBus", max_queue_size: int) -> None:
        self._bus = bus
        self._capacity = max_queue_size
        self._queue: deque[Event] = deque()
        self._closed = False

    @property
    def pending(self) -> int:
        return len(self._queue)

    async def get(self) -> Event | None:
        async with self._bus._condition:
            await self._bus._condition.wait_for(
                lambda: bool(self._queue) or self._closed or self._bus.closed
            )
            if self._queue:
                event = self._queue.popleft()
                self._bus._condition.notify_all()
                return event
            return None

    async def close(self) -> None:
        async with self._bus._condition:
            self._closed = True
            self._queue.clear()
            self._bus._subscriptions.discard(self)
            self._bus._condition.notify_all()


class EventBus:
    """Structurally implements EventSink; no workers, callbacks, retries or persistence."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._publish_lock = asyncio.Lock()
        self._subscriptions: set[EventSubscription] = set()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def subscribe(self, *, max_queue_size: int = 64) -> EventSubscription:
        if type(max_queue_size) is not int or max_queue_size <= 0:
            raise ValidationError("max_queue_size must be a positive integer")
        if self._closed:
            raise EventBusClosedError("event bus is closed")
        subscription = EventSubscription(self, max_queue_size)
        # Synchronous on the owning loop: cannot interleave with the no-await commit.
        # Adding an empty queue cannot make a previously false capacity check true.
        self._subscriptions.add(subscription)
        return subscription

    async def emit(self, event: Event) -> None:
        if not isinstance(event, Event):
            raise ValidationError("event must be Event")
        async with self._publish_lock:
            async with self._condition:
                await self._condition.wait_for(
                    lambda: (
                        self._closed
                        or all(sub.pending < sub._capacity for sub in self._subscriptions)
                    )
                )
                if self._closed:
                    raise EventBusClosedError("event bus is closed")
                # Re-evaluate membership at commit. No await between first append and return.
                for subscription in self._subscriptions:
                    subscription._queue.append(event)
                self._condition.notify_all()

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            # Handles retain their own queues so already committed events remain drainable.
            self._subscriptions.clear()
            self._condition.notify_all()
