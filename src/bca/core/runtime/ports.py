"""Stable structural ports, independent of concrete Runtime components."""

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
