import asyncio

import pytest

from bca.core.browser import TargetLostError
from bca.core.errors import LifecycleError, ValidationError
from bca.core.runtime import ActionBatch, ActionChannelState, ActionPipeline, BatchStatus, EventBus

from .action_fakes import Context, Input, action, batch, bounded, until


@pytest.mark.parametrize("count", [0, 1, 32, 33])
def test_serial_batches_and_capacity(count):
    async def run():
        provider, context = Input(), Context()
        provider.gate.clear()
        pipe = ActionPipeline(provider, context)
        await pipe.start()
        first = asyncio.create_task(pipe.submit(batch(context, 2)))
        await provider.entered.wait()
        batches = [batch(context, 2) for _ in range(count)]
        tasks = [asyncio.create_task(pipe.submit(b)) for b in batches]
        await until(lambda: pipe.snapshot().accepted == 1 + min(count, 32))
        assert pipe.snapshot().pending == min(count, 32)
        if count == 33:
            await until(lambda: pipe.snapshot().full_waits == 1)
            assert not tasks[-1].done()
        provider.gate.set()
        results = await asyncio.gather(first, *tasks)
        assert all(r.status is BatchStatus.SUCCEEDED for r in results)
        assert provider.calls[2:] == [a for b in batches for a in b.actions]
        assert pipe.snapshot().completed == count + 1
        await pipe.stop()
        assert not provider.closed

    asyncio.run(bounded(run()))


def test_empty_is_noop():
    async def run():
        provider, context = Input(), Context()
        pipe = ActionPipeline(provider, context)
        await pipe.start()
        result = await pipe.submit(ActionBatch(actions=()))
        assert result.status is BatchStatus.SUCCEEDED and result.results == ()
        assert not provider.calls
        await pipe.stop()

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("kind", ["list", "duplicate", "mixed", "reference", "id"])
def test_invalid_batch(kind):
    a = action()
    kwargs = dict(actions=(a,))
    if kind == "list":
        kwargs["actions"] = [a]
    elif kind == "duplicate":
        kwargs["actions"] = (a, a)
    elif kind == "mixed":
        kwargs["actions"] = (a, action("other"))
    elif kind == "reference":
        kwargs["observation"] = object()
    else:
        kwargs["batch_id"] = ""
    with pytest.raises(ValidationError):
        ActionBatch(**kwargs)


@pytest.mark.parametrize("where", ["capacity", "queued", "check", "execute"])
def test_cancellation_cleanup_and_no_late_input(where):
    async def run():
        provider, context = Input(), Context()
        pipe = ActionPipeline(provider, context, capacity=1)
        await pipe.start()
        if where in ("capacity", "queued"):
            provider.gate.clear()
            active = asyncio.create_task(pipe.submit(batch(context)))
            await provider.entered.wait()
            queued = asyncio.create_task(pipe.submit(batch(context)))
            await until(lambda: pipe.snapshot().pending == 1)
            target = queued
            if where == "capacity":
                target = asyncio.create_task(pipe.submit(batch(context)))
                await until(lambda: pipe.snapshot().full_waits == 1)
            target.cancel()
            with pytest.raises(asyncio.CancelledError):
                await target
            assert pipe.snapshot().pending == int(where == "capacity")
            provider.gate.set()
            await active
            if where == "capacity":
                await queued
            assert len(provider.calls) == (2 if where == "capacity" else 1)
        else:
            if where == "check":
                context.gate.clear()
            else:
                provider.gate.clear()
                provider.cleanup.clear()
            target = asyncio.create_task(pipe.submit(batch(context, 3)))
            await (context.entered if where == "check" else provider.entered).wait()
            target.cancel()
            if where == "execute":
                await provider.cleaning.wait()
                target.cancel()
                stop = asyncio.create_task(pipe.stop())
                await asyncio.sleep(0)
                assert not target.done() and not stop.done()
                provider.cleanup.set()
            with pytest.raises(asyncio.CancelledError):
                await target
            if where == "execute":
                await stop
                assert provider.cleaned and len(provider.calls) == 1
            else:
                assert not provider.calls and pipe.state is ActionChannelState.READY
        await pipe.stop()
        assert pipe.snapshot().pending == 0

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("uncertain", [False, True])
def test_first_failure_and_queued_policy(uncertain):
    async def run():
        provider, context = Input(), Context()
        provider.failure_at = 2
        provider.gate.clear()
        pipe = ActionPipeline(provider, context)
        await pipe.start()
        first = asyncio.create_task(pipe.submit(batch(context, 3)))
        await provider.entered.wait()
        second = asyncio.create_task(pipe.submit(batch(context)))
        await until(lambda: pipe.snapshot().pending == 1)
        provider.after = lambda: setattr(
            provider, "input_state_uncertain", uncertain and len(provider.calls) == 2
        )
        provider.gate.set()
        a, b = await asyncio.gather(first, second)
        assert a.status is BatchStatus.FAILED and len(a.results) == 2 and a.failed_index == 1
        assert b.status is (BatchStatus.BLOCKED if uncertain else BatchStatus.SUCCEEDED)
        assert len(provider.calls) == (2 if uncertain else 3)
        await pipe.stop()

    asyncio.run(bounded(run()))


@pytest.mark.parametrize(
    "error", [TimeoutError("private"), RuntimeError("private"), TargetLostError("private")]
)
def test_unexpected_errors_block_and_are_sanitized(error):
    async def run():
        provider, context = Input(), Context()
        provider.error = error
        pipe = ActionPipeline(provider, context)
        await pipe.start()
        result = await pipe.submit(batch(context, 2))
        assert result.status is BatchStatus.FAILED and not result.results
        assert result.error_type == type(error).__name__
        assert pipe.state is ActionChannelState.BLOCKED
        assert "private" not in repr(pipe.snapshot())
        with pytest.raises(LifecycleError):
            await pipe.submit(batch(context))
        await pipe.stop()

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("kind", ["wrong_id", "unavailable", "stale", "between"])
def test_execution_rechecks(kind):
    async def run():
        provider, context = Input(), Context()
        refreshed = []
        pipe = ActionPipeline(provider, context, request_refresh=lambda: refreshed.append(True))
        await pipe.start()
        if kind == "wrong_id":
            provider.wrong_id = True
        elif kind == "unavailable":
            provider.ready = False
        elif kind == "stale":
            context.valid = False
        else:
            provider.after = lambda: setattr(context, "valid", False)
        result = await pipe.submit(batch(context, 2))
        assert (
            result.status
            is {
                "wrong_id": BatchStatus.FAILED,
                "unavailable": BatchStatus.BLOCKED,
                "stale": BatchStatus.STALE,
                "between": BatchStatus.STALE,
            }[kind]
        )
        assert len(provider.calls) == int(kind in ("wrong_id", "between"))
        assert refreshed
        await pipe.stop()

    asyncio.run(bounded(run()))


def test_stop_shared_waiters_and_capacity_wakeup():
    async def run():
        provider, context = Input(), Context()
        provider.gate.clear()
        provider.cleanup.clear()
        pipe = ActionPipeline(provider, context, capacity=1)
        await pipe.start()
        tasks = [asyncio.create_task(pipe.submit(batch(context))) for _ in range(3)]
        await provider.entered.wait()
        await until(lambda: pipe.snapshot().pending == 1 and pipe.snapshot().full_waits >= 1)
        stop = asyncio.create_task(pipe.stop())
        await provider.cleaning.wait()
        stop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stop
        assert pipe.state is ActionChannelState.STOPPING
        provider.cleanup.set()
        await pipe.stop()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert sum(isinstance(r, LifecycleError) for r in results) == 1
        assert all(
            isinstance(r, LifecycleError) or r.status is BatchStatus.CANCELLED for r in results
        )
        assert provider.cleaned

    asyncio.run(bounded(run()))


def test_slow_bus_does_not_precede_block_or_stop():
    async def run():
        bus = EventBus()
        sub = bus.subscribe(max_queue_size=1)
        provider, context = Input(), Context()
        pipe = ActionPipeline(provider, context, bus, event_timeout=0.01)
        await pipe.start()
        await pipe.submit(batch(context))
        provider.error = RuntimeError("secret")
        await pipe.submit(batch(context))
        assert pipe.state is ActionChannelState.BLOCKED and sub.pending == 1
        await pipe.stop()
        assert pipe.snapshot().event_emit_failed == 1
        event = await sub.get()
        assert "secret" not in repr(event) and "private payload" not in repr(event)
        await bus.close()

    asyncio.run(bounded(run()))


def test_explicit_recovery_and_stop_wins():
    async def run():
        provider, context = Input(), Context()
        provider.error = TimeoutError()
        pipe = ActionPipeline(provider, context)
        await pipe.start()
        await pipe.submit(batch(context))
        replacement = Input()
        with pytest.raises(LifecycleError):
            await pipe.recover(replacement, context.reference())
        context.can_recover = True
        await pipe.recover(replacement, context.reference())
        assert (await pipe.submit(batch(context))).status is BatchStatus.SUCCEEDED
        replacement.error = TimeoutError()
        await pipe.submit(batch(context))
        context.gate.clear()
        recovery = asyncio.create_task(pipe.recover(Input(), context.reference()))
        await asyncio.sleep(0)
        await pipe.stop()
        context.gate.set()
        with pytest.raises(LifecycleError):
            await recovery
        assert pipe.state is ActionChannelState.STOPPED

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("where", ["capacity", "execute"])
def test_total_timeout_includes_wait_and_cleanup(where):
    async def run():
        provider, context = Input(), Context()
        provider.gate.clear()
        pipe = ActionPipeline(provider, context, capacity=1)
        await pipe.start()
        tasks = []
        if where == "capacity":
            tasks = [asyncio.create_task(pipe.submit(batch(context))) for _ in range(2)]
            await provider.entered.wait()
            await until(lambda: pipe.snapshot().pending == 1)
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.01):
                await pipe.submit(batch(context, 2))
        if where == "execute":
            assert provider.cleaned and len(provider.calls) == 1
            assert pipe.state is ActionChannelState.BLOCKED
        else:
            assert pipe.snapshot().accepted == 2
            provider.gate.set()
            await asyncio.gather(*tasks)
        await pipe.stop()

    asyncio.run(bounded(run()))


def test_result_delivery_cancellation_has_no_late_input():
    async def run():
        provider, context = Input(), Context()
        pipe = ActionPipeline(provider, context)
        await pipe.start()
        task = asyncio.create_task(pipe.submit(batch(context)))
        provider.after = lambda: asyncio.get_running_loop().call_soon(task.cancel)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(provider.calls) == 1
        await pipe.stop()
        assert pipe.snapshot().completed + pipe.snapshot().cancelled == 1

    asyncio.run(bounded(run()))


def test_callback_failure_cannot_kill_queue_worker():
    async def run():
        provider, context = Input(), Context()

        def refresh():
            raise RuntimeError("private")

        pipe = ActionPipeline(provider, context, request_refresh=refresh)
        await pipe.start()
        for _ in range(2):
            assert (await pipe.submit(batch(context))).status is BatchStatus.SUCCEEDED
        assert pipe.snapshot().last_error == "RuntimeError"
        await pipe.stop()

    asyncio.run(bounded(run()))


def test_notification_cancellation_cannot_leave_submissions_hanging():
    async def run():
        class CancelledSink:
            async def emit(self, event):
                raise asyncio.CancelledError()

        provider, context = Input(), Context()
        pipe = ActionPipeline(provider, context, CancelledSink())
        await pipe.start()
        results = await asyncio.gather(*(pipe.submit(batch(context)) for _ in range(3)))
        assert all(r.status is BatchStatus.SUCCEEDED for r in results)
        await pipe.stop()
        assert pipe.snapshot().event_emit_failed == 3

    asyncio.run(bounded(run()))
