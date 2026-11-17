import asyncio

import pytest

from bca.core.errors import LifecycleError, ValidationError
from bca.core.protocol import PageState, RecognitionStatus
from bca.core.runtime import EventBus, ObservationPipeline, StateStore, StateStoreClosedError


def state(status=RecognitionStatus.OK):
    return PageState(plugin_id="fake", sequence=0, recognition_status=status)


async def bounded(coro):
    async with asyncio.timeout(3):
        return await coro


@pytest.mark.parametrize("status", list(RecognitionStatus))
def test_valid_state_exactly_once_and_event_version_pair(status):
    async def run():
        store, bus = StateStore(), EventBus()
        sub = bus.subscribe()
        value = state(status)

        async def observe():
            return value

        pipeline = ObservationPipeline(observe, store, bus)
        await pipeline.run_once()
        assert store.version == 1 and store.snapshot().state is value
        event = await sub.get()
        assert event.type == "runtime.observation_completed"
        assert event.data["version"] == 1 and event.data["plugin_id"] == "fake"
        assert pipeline.snapshot().published == 1 and sub.pending == 0
        await store.close()
        await bus.close()

    asyncio.run(bounded(run()))


class Policy:
    def __init__(self, stage="valid"):
        self.stage = stage
        self.token = object()
        self.entered = asyncio.Event()
        self.cleaned = False

    async def step(self, name):
        if self.stage == name + "_error":
            raise ValueError("private details")
        if self.stage == name + "_wait":
            self.entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cleaned = True

    async def begin(self):
        await self.step("begin")
        return self.token

    async def validate(self, token, value):
        assert token is self.token and isinstance(value, PageState)
        await self.step("validate")
        return self.stage != "stale"


@pytest.mark.parametrize(
    "failure", ["stale", "begin_error", "validate_error", "invalid", "observe_error"]
)
def test_failure_and_stale_do_not_publish_and_notify_once(failure):
    async def run():
        store, bus = StateStore(), EventBus()
        sub = bus.subscribe()

        async def observe():
            if failure == "observe_error":
                raise ValueError("secret")
            return {} if failure == "invalid" else state()

        pipeline = ObservationPipeline(observe, store, bus, freshness=Policy(failure))
        await pipeline.run_once()
        assert store.version == 0
        result = await sub.get()
        assert result.type == (
            "runtime.observation_stale" if failure == "stale" else "runtime.observation_failed"
        )
        stats = pipeline.snapshot()
        assert stats.stale == int(failure == "stale") and stats.failed == int(failure != "stale")
        assert sub.pending == 0 and "secret" not in str(result.data)
        await store.close()
        await bus.close()

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("stage", ["begin", "observe", "validate", "publish"])
@pytest.mark.parametrize("mode", ["cancel", "timeout"])
def test_observation_budget_and_cancellation_cover_all_stages(stage, mode):
    async def run():
        policy = Policy(stage + "_wait")
        entered = policy.entered
        cleaned = asyncio.Event()

        class WaitingStore(StateStore):
            async def publish(self, value):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaned.set()

        store = WaitingStore() if stage == "publish" else StateStore()

        async def observe():
            if stage == "observe":
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaned.set()
            return state()

        pipeline = ObservationPipeline(
            observe, store, freshness=policy, observation_timeout=0.01 if mode == "timeout" else 10
        )
        task = asyncio.create_task(pipeline.run_once())
        await entered.wait()
        if mode == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert pipeline.snapshot().cancelled == 1
        else:
            await task
            assert pipeline.snapshot().timed_out == 1 and pipeline.snapshot().failed == 1
        assert store.version == 0
        assert policy.cleaned if stage in ("begin", "validate") else cleaned.is_set()
        await store.close()

    asyncio.run(bounded(run()))


def test_concurrent_calls_serialize_and_pair_versions_with_states():
    async def run():
        store, bus = StateStore(), EventBus()
        sub = bus.subscribe()
        active = peak = count = 0

        async def observe():
            nonlocal active, peak, count
            active += 1
            peak = max(peak, active)
            count += 1
            await asyncio.sleep(0)
            active -= 1
            return PageState(plugin_id="fake", sequence=count, source_frame_id=str(count))

        pipeline = ObservationPipeline(observe, store, bus)
        await asyncio.gather(*(pipeline.run_once() for _ in range(20)))
        assert peak == 1 and store.version == 20
        for n in range(1, 21):
            message = await sub.get()
            assert message.data["version"] == n and message.data["source_frame_id"] == str(n)
        await store.close()
        await bus.close()

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("mode", ["timeout", "closed", "cancel"])
def test_notification_failure_or_cancel_never_republishes(mode):
    async def run():
        store, bus = StateStore(), EventBus()
        sub = bus.subscribe(max_queue_size=1)

        async def observe():
            return state()

        pipeline = ObservationPipeline(
            observe, store, bus, event_timeout=0.01 if mode == "timeout" else 10
        )
        await pipeline.run_once()
        if mode == "closed":
            await bus.close()
        task = asyncio.create_task(pipeline.run_once())
        await store.wait_for_update(1)
        if mode == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
        assert store.version == 2 and pipeline.snapshot().published == 2
        assert pipeline.snapshot().event_emit_failed == 1 and sub.pending == 1
        await store.close()
        await bus.close()

    asyncio.run(bounded(run()))


def test_closed_store_and_incorrect_writer_pairing_are_fatal():
    async def run():
        async def observe():
            return state()

        store = StateStore()
        await store.close()
        pipeline = ObservationPipeline(observe, store)
        with pytest.raises(StateStoreClosedError):
            await pipeline.run_once()
        assert pipeline.snapshot().failed == 1

        class InterferedStore(StateStore):
            async def publish(self, value):
                await super().publish(value)
                await super().publish(state())

        store = InterferedStore()
        bus = EventBus()
        sub = bus.subscribe()
        pipeline = ObservationPipeline(observe, store, bus)
        with pytest.raises(LifecycleError):
            await pipeline.run_once()
        assert pipeline.snapshot().published == 1 and store.version == 2 and sub.pending == 0
        await store.close()
        await bus.close()

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("invalid", [False, 0, -1, float("nan"), float("inf"), "1"])
@pytest.mark.parametrize("parameter", ["observation_timeout", "event_timeout"])
def test_invalid_budget(invalid, parameter):
    with pytest.raises(ValidationError):
        ObservationPipeline(lambda: None, StateStore(), **{parameter: invalid})


@pytest.mark.parametrize("stage", ["valid", "stale", "closed"])
def test_commit_hook_pairs_exact_store_snapshot(stage):
    async def run():
        store = StateStore()
        policy = Policy("stale" if stage == "stale" else "valid")
        committed = []

        def commit(token, snapshot):
            assert token is policy.token
            assert snapshot is store.snapshot()
            committed.append(snapshot)

        async def observe():
            return state()

        pipeline = ObservationPipeline(observe, store, freshness=policy, on_commit=commit)
        if stage == "closed":
            await store.close()
            with pytest.raises(StateStoreClosedError):
                await pipeline.run_once()
        else:
            await pipeline.run_once()
        assert len(committed) == int(stage == "valid")

    asyncio.run(bounded(run()))
