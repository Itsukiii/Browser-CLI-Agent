import asyncio

import pytest

from bca.core.errors import LifecycleError
from bca.core.runtime import (
    ActionChannelState,
    BatchStatus,
    RuntimeController,
    SchedulerState,
    StateStore,
)

from .action_fakes import Context, Input, batch, bounded, observe, until


def test_lifecycle_and_borrowed_ownership():
    async def run():
        states, provider, context = StateStore(), Input(), Context()
        controller = RuntimeController(observe, provider, states, context, interval=100)
        await controller.start()
        await controller.start()
        await states.wait_for_update(0)
        await controller.pause()
        await controller.pause()
        result = await controller.submit(batch(context))
        assert result.status is BatchStatus.SUCCEEDED
        assert controller.state is SchedulerState.PAUSED
        await controller.resume()
        await controller.resume()
        await states.wait_for_update(1)
        await controller.stop()
        await controller.stop()
        assert controller.snapshot().action_state is ActionChannelState.STOPPED
        assert not provider.closed and not states.closed
        for operation in (controller.start, controller.pause, controller.resume):
            with pytest.raises(LifecycleError):
                await operation()
        with pytest.raises(LifecycleError):
            await controller.submit(batch(context))

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("failure", ["provider", "store", "scheduler"])
def test_partial_start_failure_cleans_owned_components(failure):
    async def run():
        states, provider, context = StateStore(), Input(), Context()
        controller = RuntimeController(observe, provider, states, context)
        if failure == "provider":
            provider.ready = False
        elif failure == "store":
            await states.close()
        else:

            async def fail():
                raise RuntimeError("injected")

            controller.scheduler.start = fail
        with pytest.raises((LifecycleError, RuntimeError)):
            await controller.start()
        assert controller.state is SchedulerState.STOPPED
        assert controller.actions.state is ActionChannelState.STOPPED
        assert not provider.closed

    asyncio.run(bounded(run()))


def test_observation_commit_and_input_never_interleave():
    async def run():
        states, provider, context = StateStore(), Input(), Context()
        observing, release = asyncio.Event(), asyncio.Event()

        async def held_observe():
            observing.set()
            await release.wait()
            return await observe()

        controller = RuntimeController(held_observe, provider, states, context, interval=100)
        old = batch(context)
        await controller.start()
        await observing.wait()
        submit = asyncio.create_task(controller.submit(old))
        await until(lambda: controller.actions.snapshot().executed == 1)
        assert not provider.calls and not context.entered.is_set()
        release.set()
        assert (await submit).status is BatchStatus.STALE
        await controller.pause()
        provider.gate.clear()
        submit = asyncio.create_task(controller.submit(batch(context, 2)))
        await provider.entered.wait()
        version = states.version
        await controller.resume()
        await asyncio.sleep(0)
        assert states.version == version
        provider.gate.set()
        assert (await submit).status is BatchStatus.SUCCEEDED
        await states.wait_for_update(version)
        await controller.stop()

    asyncio.run(bounded(run()))


def test_stop_wins_pause_and_cancelled_stop_waiter():
    async def run():
        states, provider, context = StateStore(), Input(), Context()
        entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def held():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()

        controller = RuntimeController(held, provider, states, context)
        await controller.start()
        await entered.wait()
        pause = asyncio.create_task(controller.pause())
        await asyncio.sleep(0)
        stop = asyncio.create_task(controller.stop())
        await cleaning.wait()
        with pytest.raises(LifecycleError):
            await controller.submit(batch(context))
        stop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stop
        release.set()
        await controller.stop()
        with pytest.raises(LifecycleError):
            await pause
        assert controller.state is SchedulerState.STOPPED

    asyncio.run(bounded(run()))


def test_blocked_actions_do_not_stop_observation():
    async def run():
        states, provider, context = StateStore(), Input(), Context()
        controller = RuntimeController(observe, provider, states, context, interval=100)
        await controller.start()
        await states.wait_for_update(0)
        await controller.pause()
        provider.error = TimeoutError()
        await controller.submit(batch(context))
        assert controller.actions.state is ActionChannelState.BLOCKED
        await controller.resume()
        await states.wait_for_update(1)
        assert controller.state is SchedulerState.RUNNING
        await controller.stop()

    asyncio.run(bounded(run()))


def test_controller_self_stop_rejected_without_deadlock():
    async def run():
        states, provider, context = StateStore(), Input(), Context()
        entered = asyncio.Event()

        async def observe_self_stop():
            with pytest.raises(LifecycleError):
                await controller.stop()
            entered.set()
            return await observe()

        controller = RuntimeController(observe_self_stop, provider, states, context)
        await controller.start()
        await entered.wait()
        assert controller.state is SchedulerState.RUNNING
        await controller.stop()

    asyncio.run(bounded(run()))
