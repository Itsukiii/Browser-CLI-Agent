import asyncio

import pytest

from bca.core.errors import LifecycleError, ValidationError
from bca.core.protocol import Event, PageState
from bca.core.runtime import EventBus, EventBusClosedError, StateStore


def event(n=0):
    return Event(type="test.event", source="test", data={"n": n})


def test_zero_subscribers_identity_fifo_and_default_capacity():
    async def run():
        bus = EventBus()
        assert await bus.emit(event(-1)) is None
        first, second = bus.subscribe(), bus.subscribe()
        events = [event(n) for n in range(64)]
        for item in events:
            assert await bus.emit(item) is None
        assert first.pending == second.pending == 64
        extra = event(64)
        pending = asyncio.create_task(bus.emit(extra))
        await asyncio.sleep(0)
        assert not pending.done()
        for sub in (first, second):
            assert await sub.get() is events[0]
        await pending
        await bus.close()
        for sub in (first, second):
            for item in events[1:] + [extra]:
                assert await sub.get() is item
            assert await sub.get() is None and sub.pending == 0
        await bus.close()

    asyncio.run(run())


@pytest.mark.parametrize("abort", ["cancel", "timeout", "close"])
def test_no_partial_delivery_when_only_one_subscriber_full(abort):
    async def run():
        bus = EventBus()
        fast, slow = bus.subscribe(max_queue_size=1), bus.subscribe(max_queue_size=1)
        initial = event()
        await bus.emit(initial)
        assert await fast.get() is initial
        timeout_scope = asyncio.timeout(None)

        async def publish():
            async with timeout_scope:
                await bus.emit(event(1))

        pending = asyncio.create_task(publish())
        await asyncio.sleep(0)
        assert fast.pending == 0 and slow.pending == 1 and not pending.done()
        if abort == "close":
            await bus.close()
            with pytest.raises(EventBusClosedError):
                await pending
        elif abort == "timeout":
            timeout_scope.reschedule(asyncio.get_running_loop().time())
            with pytest.raises(TimeoutError):
                await pending
        else:
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        assert fast.pending == 0 and slow.pending == 1
        assert await slow.get() is initial
        await bus.close()
        assert await fast.get() is None and await slow.get() is None

    asyncio.run(run())


def test_commit_membership_new_subscriber_and_retirement():
    async def run():
        bus = EventBus()
        blocker, recipient = bus.subscribe(max_queue_size=1), bus.subscribe(max_queue_size=1)
        initial, next_event = event(), event(1)
        await bus.emit(initial)
        await recipient.get()
        pending = asyncio.create_task(bus.emit(next_event))
        await asyncio.sleep(0)
        newcomer = bus.subscribe(max_queue_size=1)
        retired = bus.subscribe()
        await retired.close()
        await blocker.close()  # Drop backlog and release the publisher's capacity wait.
        await pending
        assert await blocker.get() is None and blocker.pending == 0
        assert await retired.get() is None
        assert await recipient.get() is next_event and await newcomer.get() is next_event
        late = bus.subscribe()
        assert late.pending == 0
        await bus.close()
        assert await late.get() is None

    asyncio.run(run())


def test_concurrent_publishers_have_same_order_under_backpressure():
    async def run():
        bus = EventBus()
        subs = [bus.subscribe(max_queue_size=size) for size in (1, 2, 3)]

        async def consume(sub):
            result = []
            while (item := await sub.get()) is not None:
                result.append(item)
                await asyncio.sleep(0)
            return result

        readers = [asyncio.create_task(consume(sub)) for sub in subs]
        items = [event(n) for n in range(100)]
        await asyncio.gather(*(bus.emit(item) for item in items))
        await bus.close()
        outputs = await asyncio.gather(*readers)
        assert all(output == items for output in outputs)
        assert all(output[n] is items[n] for output in outputs for n in range(100))

    asyncio.run(run())


def test_cancel_publisher_waiting_for_serial_lock_and_cancel_reader():
    async def run():
        bus = EventBus()
        sub = bus.subscribe(max_queue_size=1)
        initial, second = event(), event(1)
        await bus.emit(initial)
        first = asyncio.create_task(bus.emit(second))
        cancelled = asyncio.create_task(bus.emit(event(2)))
        await asyncio.sleep(0)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        assert await sub.get() is initial
        await first
        assert await sub.get() is second
        readers = [asyncio.create_task(sub.get()) for _ in range(2)]
        await asyncio.sleep(0)
        readers[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await readers[0]
        await bus.emit(initial)
        assert await readers[1] is initial
        await bus.close()

    asyncio.run(run())


def test_close_wakes_capacity_lock_and_reader_waiters_without_workers():
    async def run():
        before = asyncio.all_tasks()
        bus = EventBus()
        slow = bus.subscribe(max_queue_size=1)
        await bus.emit(event())
        empty = bus.subscribe()
        reader = asyncio.create_task(empty.get())
        writers = [asyncio.create_task(bus.emit(event(n))) for n in range(10)]
        await asyncio.sleep(0)
        await asyncio.gather(bus.close(), bus.close())
        errors = await asyncio.gather(*writers, return_exceptions=True)
        assert all(isinstance(e, (EventBusClosedError, LifecycleError)) for e in errors)
        assert await reader is None
        assert slow.pending == 1  # Bus close drains; explicit subscription close discards.
        await slow.close()
        await slow.close()
        assert await slow.get() is None and slow.pending == 0
        with pytest.raises(EventBusClosedError):
            bus.subscribe()
        with pytest.raises(EventBusClosedError):
            await bus.emit(event())
        assert asyncio.all_tasks() == before

    asyncio.run(run())


def test_subscription_close_wakes_all_readers_and_all_retired_emit_succeeds():
    async def run():
        bus = EventBus()
        sub = bus.subscribe(max_queue_size=1)
        readers = [asyncio.create_task(sub.get()) for _ in range(3)]
        await asyncio.sleep(0)
        await sub.close()
        assert await asyncio.gather(*readers) == [None, None, None]
        full = bus.subscribe(max_queue_size=1)
        await bus.emit(event())
        pending = asyncio.create_task(bus.emit(event()))
        await asyncio.sleep(0)
        await full.close()
        assert await pending is None
        await bus.close()

    asyncio.run(run())


@pytest.mark.parametrize("size", [True, False, 0, -1, 1.0, "1", None])
def test_invalid_capacity(size):
    with pytest.raises(ValidationError):
        EventBus().subscribe(max_queue_size=size)


def test_invalid_event_and_independent_state_commit():
    async def run():
        store, bus = StateStore(), EventBus()
        with pytest.raises(ValidationError):
            await bus.emit({})
        await store.publish(PageState(plugin_id="test", sequence=0))
        await bus.close()
        with pytest.raises(EventBusClosedError):
            await bus.emit(event())
        assert store.version == 1
        await store.close()

    asyncio.run(run())


def test_cancellation_after_commit_does_not_revoke_event():
    async def run():
        bus = EventBus()
        first, second = bus.subscribe(), bus.subscribe()
        item = event()
        publisher = asyncio.create_task(bus.emit(item))
        await asyncio.sleep(0)
        assert publisher.done() and publisher.cancel() is False
        assert await publisher is None
        await bus.close()
        assert await first.get() is item and await second.get() is item

    asyncio.run(run())
