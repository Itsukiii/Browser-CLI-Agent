"""Simulated periodic observation, notification, immediate request and pause/resume."""

import asyncio
from dataclasses import asdict

from bca.core.protocol import PageState
from bca.core.runtime import EventBus, ObservationPipeline, Scheduler, StateStore


async def main() -> None:
    store, bus = StateStore(), EventBus()
    subscription = bus.subscribe()
    sequence = 0

    async def observe() -> PageState:
        nonlocal sequence
        sequence += 1
        return PageState(plugin_id="simulated", sequence=sequence, data={"ready": True})

    pipeline = ObservationPipeline(observe, store, bus)
    scheduler = Scheduler(pipeline.run_once)  # Default fixed period is 100 ms.
    try:
        await scheduler.start()
        async with asyncio.timeout(3):
            await store.wait_for_update(1)  # Initial observation plus a periodic observation.
            previous = store.version
            scheduler.request_immediate()
            await store.wait_for_update(previous)
            await scheduler.pause()
            paused_version = store.version
            scheduler.request_immediate()  # Retained as one bit; resume triggers just one round.
            await scheduler.resume()
            await store.wait_for_update(paused_version)
            await scheduler.pause()
        await scheduler.stop()
        await bus.close()
        versions = []
        while (event := await subscription.get()) is not None:
            versions.append(event.data["version"])
        print(f"latest_version={store.version}; notification_versions={versions}")
        print(f"scheduler={asdict(scheduler.snapshot())}")
        print(f"pipeline={asdict(pipeline.snapshot())}")
    finally:
        await scheduler.stop()  # Does not close any borrowed objects.
        await subscription.close()
        await bus.close()
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
