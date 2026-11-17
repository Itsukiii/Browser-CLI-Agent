import asyncio
from dataclasses import FrozenInstanceError

import pytest

from bca.core.errors import LifecycleError, ValidationError
from bca.core.protocol import PageState
from bca.core.runtime import StateSnapshot, StateStore, StateStoreClosedError


def state(sequence=0):
    return PageState(plugin_id="test", sequence=sequence, data={"value": 1})


def test_versions_identity_and_latest_only():
    async def run():
        store = StateStore()
        assert store.version == 0 and store.snapshot() is None and not store.closed
        same = state(50)
        for _ in range(99):
            assert await store.publish(same) is None
        reset = state(0)
        await store.publish(reset)
        snapshot = store.snapshot()
        assert snapshot.version == 100 and snapshot.state is reset
        assert snapshot.state.sequence == 0 and same.sequence == 50
        assert await store.wait_for_update(0) is snapshot
        with pytest.raises(FrozenInstanceError):
            snapshot.version = 1
        await store.close()
        assert await store.wait_for_update(99) is snapshot
        assert await store.wait_for_update(100) is None
        assert await store.wait_for_update(1000) is None
        with pytest.raises(StateStoreClosedError):
            await store.publish(same)
        assert store.version == 100
        await store.close()

    asyncio.run(run())


def test_waiters_cancel_future_cursor_and_coalescing():
    async def run():
        store = StateStore()
        tasks = [asyncio.create_task(store.wait_for_update(0)) for _ in range(4)]
        future = asyncio.create_task(store.wait_for_update(3))
        await asyncio.sleep(0)  # Register all waiters before mutation, no wall-clock sleeps.
        tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[0]
        for n in range(3):
            await store.publish(state(n))
        assert [s.version for s in await asyncio.gather(*tasks[1:])] == [3, 3, 3]
        assert not future.done()
        await store.publish(state())
        assert (await future).version == 4
        waiting = asyncio.create_task(store.wait_for_update(4))
        await asyncio.sleep(0)
        await store.close()
        assert await waiting is None

    asyncio.run(run())


@pytest.mark.parametrize("publish_first", [False, True])
def test_registration_and_publish_close_order(publish_first):
    async def run():
        store = StateStore()
        for version in range(30):
            coroutines = [store.wait_for_update(version), store.publish(state())]
            if publish_first:
                coroutines.reverse()
            results = await asyncio.gather(*coroutines)
            assert next(r for r in results if r is not None).version == version + 1
        work = [store.publish(state()), store.close()]
        if not publish_first:
            work.reverse()
        results = await asyncio.gather(*work, return_exceptions=True)
        assert store.version == (31 if publish_first else 30)
        if not publish_first:
            assert isinstance(results[1], StateStoreClosedError)
            assert isinstance(results[1], LifecycleError)
        assert store.closed

    asyncio.run(run())


@pytest.mark.parametrize("invalid", [True, False, -1, 1.0, "0", None])
def test_cursor_validation(invalid):
    async def run():
        store = StateStore()
        with pytest.raises(ValidationError):
            await store.wait_for_update(invalid)
        await store.close()

    asyncio.run(run())


def test_type_validation_and_close_empty():
    async def run():
        store = StateStore()
        with pytest.raises(ValidationError):
            await store.publish({})
        waiter = asyncio.create_task(store.wait_for_update(0))
        await asyncio.sleep(0)
        await asyncio.gather(store.close(), store.close())
        assert await waiter is None and store.snapshot() is None
        with pytest.raises(ValidationError):
            StateSnapshot(version=True, state=state())
        with pytest.raises(ValidationError):
            StateSnapshot(version=1, state={})

    asyncio.run(run())


def test_close_after_commit_preserves_update_for_registered_waiter():
    async def run():
        store = StateStore()
        waiter = asyncio.create_task(store.wait_for_update(0))
        await asyncio.sleep(0)
        await store.publish(state())
        await store.close()
        assert (await waiter).version == 1
        assert await store.wait_for_update(1) is None

    asyncio.run(run())
