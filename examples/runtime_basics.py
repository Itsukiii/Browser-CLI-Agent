"""Run with python examples/runtime_basics.py; no browser required."""

import asyncio

from bca.core.protocol import Event, PageState
from bca.core.runtime import EventBus, EventSink, StateSink, StateStore


async def main() -> None:
    store, bus = StateStore(), EventBus()
    states: StateSink = store
    events: EventSink = bus
    first, second = bus.subscribe(max_queue_size=2), bus.subscribe(max_queue_size=2)
    try:
        await states.publish(PageState(plugin_id="example", sequence=0, data={"ready": True}))
        snapshot = await store.wait_for_update(0)
        assert snapshot is not None
        # This example is the sole publisher. Concurrent pipelines must serialize this pairing.
        event = Event(
            type="runtime.state_updated", source="example", data={"version": snapshot.version}
        )
        await events.emit(event)
        assert await first.get() is event and await second.get() is event
        print(f"version={snapshot.version}; two subscribers received the same Event")
    finally:
        await store.close()
        await bus.close()
        await first.close()
        await second.close()


if __name__ == "__main__":
    asyncio.run(main())
