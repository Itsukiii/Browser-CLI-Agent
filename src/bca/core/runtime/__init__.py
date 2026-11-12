"""Runtime ports. Scheduler and event bus implementations belong to a later stage."""

from typing import Protocol

from bca.core.protocol import Event, PageState


class StateSink(Protocol):
    async def publish(self, state: PageState) -> None:
        """Accept a state with backpressure; ownership transfers on successful return."""
        ...


class EventSink(Protocol):
    async def emit(self, event: Event) -> None:
        """Accept an event with backpressure; failures propagate to the caller."""
        ...


__all__ = ["EventSink", "StateSink"]
