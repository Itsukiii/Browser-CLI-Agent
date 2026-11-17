import asyncio

from bca.core.runtime import EventBus, ObservationPipeline, SchedulerState, StateStore

from .test_observation import state
from .test_scheduler import ClockScheduler, bounded


def test_full_bus_bounded_notifications_continue_observation_and_stop_owns_only_tasks():
    async def run():
        before = asyncio.all_tasks()
        store, bus = StateStore(), EventBus()
        subscriber = bus.subscribe(max_queue_size=1)

        async def observe():
            return state()

        pipeline = ObservationPipeline(observe, store, bus, event_timeout=0.01)
        scheduler = ClockScheduler(pipeline.run_once, automatic=True)
        await scheduler.start()
        await store.wait_for_update(2)
        await scheduler.stop()
        assert store.version == 3
        assert pipeline.snapshot().published == 3
        assert pipeline.snapshot().event_emit_failed >= 1
        assert subscriber.pending == 1
        assert not store.closed and not bus.closed
        assert scheduler.state is SchedulerState.STOPPED
        assert asyncio.all_tasks() == before
        assert (await subscriber.get()).data["version"] == 1
        await store.close()
        await bus.close()

    asyncio.run(bounded(run()))


def test_observe_timeout_finishes_cleanup_before_next_attempt():
    async def run():
        store = StateStore()
        cleaned = False
        attempts = 0

        async def observe():
            nonlocal cleaned, attempts
            attempts += 1
            if attempts == 1:
                try:
                    await asyncio.Event().wait()
                finally:
                    await asyncio.sleep(0)
                    cleaned = True
            assert cleaned
            return state()

        pipeline = ObservationPipeline(observe, store, observation_timeout=0.01)
        scheduler = ClockScheduler(pipeline.run_once, automatic=True)
        await scheduler.start()
        await store.wait_for_update(0)
        await scheduler.stop()
        assert attempts == 2 and pipeline.snapshot().timed_out == 1
        assert store.version == 1 and not store.closed
        await store.close()

    asyncio.run(bounded(run()))


def test_closed_store_stops_scheduler_without_repeated_structural_errors():
    async def run():
        store = StateStore()
        await store.close()
        calls = 0

        async def observe():
            nonlocal calls
            calls += 1
            return state()

        pipeline = ObservationPipeline(observe, store)
        scheduler = ClockScheduler(pipeline.run_once, automatic=True)
        await scheduler.start()
        await scheduler._worker
        assert calls == 0 and pipeline.snapshot().attempts == 1
        assert scheduler.state is SchedulerState.STOPPED
        assert scheduler.snapshot().last_error == "StateStoreClosedError"
        await scheduler.stop()

    asyncio.run(bounded(run()))


def test_cancel_queued_pipeline_call_does_not_cancel_active_observer():
    async def run():
        store = StateStore()
        entered, release = asyncio.Event(), asyncio.Event()

        async def observe():
            entered.set()
            await release.wait()
            return state()

        pipeline = ObservationPipeline(observe, store)
        active = asyncio.create_task(pipeline.run_once())
        await entered.wait()
        queued = asyncio.create_task(pipeline.run_once())
        await asyncio.sleep(0)
        queued.cancel()
        try:
            await queued
        except asyncio.CancelledError:
            pass
        assert not active.done() and pipeline.snapshot().attempts == 1
        release.set()
        await active
        assert store.version == 1 and pipeline.snapshot().cancelled == 0
        await store.close()

    asyncio.run(bounded(run()))
