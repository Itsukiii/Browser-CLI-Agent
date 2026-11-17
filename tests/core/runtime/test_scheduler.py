import asyncio
from dataclasses import FrozenInstanceError

import pytest

from bca.core.errors import LifecycleError, ValidationError
from bca.core.runtime import Scheduler, SchedulerState


async def bounded(coro):
    async with asyncio.timeout(3):
        return await coro


class ClockScheduler(Scheduler):
    """Controllable monotonic clock; no real timer sleeps in cadence tests."""

    def __init__(self, operation, *, automatic=False):
        super().__init__(operation, interval=1)
        self.now = 0.0
        self.automatic = automatic
        self.waiting = asyncio.Event()

    def _now(self):
        return self.now

    async def _wait(self, delay):
        self.waiting.set()
        if self.automatic and delay is not None:
            self.now += delay
            await asyncio.sleep(0)
        else:
            await self._wake.wait()


@pytest.mark.parametrize("interval", [True, False, 0, -1, float("nan"), float("inf"), "1", None])
def test_invalid_interval(interval):
    with pytest.raises(ValidationError):
        Scheduler(lambda: None, interval=interval)


@pytest.mark.parametrize(
    "duration,starts,skipped",
    [
        (0.2, [0, 1, 2], 0),
        (1, [0, 1, 2], 0),
        (1.2, [0, 2, 4], 2),
        (3.2, [0, 4, 8], 6),
    ],
)
def test_fixed_rate_skip_and_exact_boundary(duration, starts, skipped):
    async def run():
        seen = []
        finished = asyncio.Event()

        async def operation():
            seen.append(scheduler.now)
            if len(seen) == 3:
                finished.set()
                raise LifecycleError("done")
            scheduler.now += duration

        scheduler = ClockScheduler(operation, automatic=True)
        await scheduler.start()
        await finished.wait()
        assert seen == starts
        assert scheduler.state is SchedulerState.STOPPED
        assert scheduler.snapshot().skipped_ticks == skipped
        assert scheduler.snapshot().periodic_runs == 3
        await scheduler.stop()

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("requests", [1, 10, 100])
@pytest.mark.parametrize("also_periodic", [False, True])
def test_busy_requests_coalesce_and_due_tick_is_not_duplicated(requests, also_periodic):
    async def run():
        entered, release, second = asyncio.Event(), asyncio.Event(), asyncio.Event()
        active = peak = calls = 0

        async def operation():
            nonlocal active, peak, calls
            active += 1
            peak = max(peak, active)
            calls += 1
            try:
                if calls == 1:
                    entered.set()
                    await release.wait()
                else:
                    second.set()
            finally:
                active -= 1

        scheduler = ClockScheduler(operation)
        await scheduler.start()
        await entered.wait()
        for _ in range(requests):
            scheduler.request_immediate()
        scheduler.now = 1 if also_periodic else 0.2
        release.set()
        await second.wait()
        await scheduler.waiting.wait()
        assert calls == 2 and peak == 1
        stats = scheduler.snapshot()
        assert stats.coalesced_requests == requests - 1
        assert stats.immediate_runs == int(not also_periodic)
        assert stats.periodic_runs == 1 + int(also_periodic)
        await scheduler.stop()

    asyncio.run(bounded(run()))


def test_default_lifecycle_idle_immediate_and_frozen_stats():
    async def run():
        called = asyncio.Event()

        async def operation():
            called.set()

        scheduler = Scheduler(operation)
        assert scheduler._interval == 0.1 and scheduler.state is SchedulerState.CREATED
        scheduler.request_immediate()
        scheduler.request_immediate()
        with pytest.raises(LifecycleError):
            await scheduler.pause()
        with pytest.raises(LifecycleError):
            await scheduler.resume()
        await scheduler.start()
        await scheduler.start()
        await called.wait()
        await scheduler.pause()
        assert scheduler.snapshot().started == 1
        with pytest.raises(FrozenInstanceError):
            scheduler.snapshot().started = 0
        await scheduler.resume()
        await scheduler.resume()
        await scheduler.pause()
        await scheduler.stop()
        await scheduler.stop()
        assert scheduler.state is SchedulerState.STOPPED
        with pytest.raises(LifecycleError):
            scheduler.request_immediate()
        with pytest.raises(LifecycleError):
            await scheduler.start()
        with pytest.raises(LifecycleError):
            await scheduler.resume()
        await scheduler.pause()
        never_started = Scheduler(operation)
        await never_started.stop()
        with pytest.raises(LifecycleError):
            await never_started.start()

    asyncio.run(bounded(run()))


def test_pause_natural_completion_cancelled_waiter_resume_resets_epoch():
    async def run():
        entered, release, resumed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        starts = []

        async def operation():
            starts.append(scheduler.now)
            if len(starts) == 1:
                entered.set()
                await release.wait()
            else:
                resumed.set()

        scheduler = ClockScheduler(operation)
        await scheduler.start()
        await entered.wait()
        pausing = asyncio.create_task(scheduler.pause())
        await asyncio.sleep(0)
        assert not pausing.done() and scheduler.state is SchedulerState.PAUSED
        pausing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pausing
        for _ in range(10):
            scheduler.request_immediate()
        release.set()
        await scheduler.pause()
        await asyncio.sleep(0)
        assert starts == [0]
        scheduler.now = 50
        await scheduler.resume()
        await resumed.wait()
        await scheduler.waiting.wait()
        assert starts == [0, 50] and scheduler._anchor == 50
        scheduler.now = 50.25
        resumed.clear()
        scheduler.request_immediate()
        await resumed.wait()
        assert starts[-1] == 50.25
        await scheduler.stop()

    asyncio.run(bounded(run()))


def test_stop_wins_pause_and_waits_for_cancel_cleanup_even_if_caller_cancelled():
    async def run():
        before = asyncio.all_tasks()
        entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def operation():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()

        scheduler = Scheduler(operation)
        await scheduler.start()
        await entered.wait()
        pausing = asyncio.create_task(scheduler.pause())
        stopping = asyncio.create_task(scheduler.stop())
        await cleaning.wait()
        assert not pausing.done() and not stopping.done()
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        with pytest.raises(LifecycleError):
            scheduler.request_immediate()
        release.set()
        await asyncio.gather(pausing, scheduler.stop(), scheduler.stop())
        assert scheduler.state is SchedulerState.STOPPED
        assert scheduler.snapshot().cancelled == 1
        assert asyncio.all_tasks() == before

    asyncio.run(bounded(run()))


def test_recoverable_error_continues_and_fatal_error_stops():
    async def run():
        calls = 0
        done = asyncio.Event()

        async def operation():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("sensitive text")
            done.set()
            raise LifecycleError("fatal")

        scheduler = ClockScheduler(operation, automatic=True)
        await scheduler.start()
        await done.wait()
        assert scheduler.state is SchedulerState.STOPPED
        assert scheduler.snapshot().failed == 2
        assert scheduler.snapshot().last_error == "LifecycleError"
        await scheduler.stop()

    asyncio.run(bounded(run()))


def test_resume_waiting_for_cancelled_pause_cannot_override_stop():
    async def run():
        entered = asyncio.Event()
        cleaned = asyncio.Event()

        async def operation():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        scheduler = Scheduler(operation)
        await scheduler.start()
        await entered.wait()
        pausing = asyncio.create_task(scheduler.pause())
        await asyncio.sleep(0)
        pausing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pausing
        resuming = asyncio.create_task(scheduler.resume())
        await asyncio.sleep(0)
        assert not resuming.done()
        scheduler.request_immediate()
        await scheduler.stop()
        with pytest.raises(LifecycleError):
            await resuming
        assert cleaned.is_set() and scheduler.snapshot().started == 1
        assert scheduler.state is SchedulerState.STOPPED

    asyncio.run(bounded(run()))


def test_operation_cannot_await_own_scheduler_lifecycle():
    async def run():
        async def operation():
            await scheduler.pause()

        scheduler = Scheduler(operation)
        await scheduler.start()
        await scheduler._worker
        assert scheduler.state is SchedulerState.STOPPED
        assert scheduler.snapshot().last_error == "LifecycleError"
        await scheduler.stop()

    asyncio.run(bounded(run()))
