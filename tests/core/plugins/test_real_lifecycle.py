import asyncio
import os

import pytest

from bca.core.errors import LifecycleError
from bca.core.plugins import PluginLifecycleState

from .real_helpers import harness, run, started

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(
        not os.environ.get("BCA_CDP_ENDPOINT"), reason="explicit isolated CDP required"
    ),
]


@pytest.mark.parametrize("stage", ["initialize", "start", "stop", "close"])
@pytest.mark.parametrize("cancel", [False, True])
def test_real_owned_plugin_task_cleanup(stage, cancel, tmp_path):
    async def case():
        async with harness(tmp_path) as h:
            part = h["part"]
            plugin = part.manager._plugin
            background = None
            entered = asyncio.Event()
            original_init, original_stop = plugin.initialize, plugin.stop

            async def initialize(context):
                nonlocal background
                await original_init(context)
                background = asyncio.create_task(asyncio.Event().wait(), name="fixture-owned")
                if stage == "initialize":
                    await fail()

            async def fail():
                entered.set()
                if cancel:
                    raise asyncio.CancelledError()
                raise ValueError("fixture-private-failure")

            async def close():
                if background:
                    background.cancel()
                    await asyncio.gather(background, return_exceptions=True)
                await original_stop()
                plugin.context = None
                plugin.frame = None
                if stage == "close":
                    await fail()

            plugin.initialize, plugin.close = initialize, close
            if stage in ("start", "stop"):
                setattr(plugin, stage, fail)
            if stage in ("initialize", "start"):
                with pytest.raises(asyncio.CancelledError if cancel else ValueError):
                    await part.start()
            else:
                await started(h)
                if stage == "stop":
                    with pytest.raises(asyncio.CancelledError if cancel else ValueError):
                        await part.host.close()
                else:
                    # Manager archives close errors; application must inspect snapshot.
                    await part.host.close()
            assert entered.is_set()
            assert background is not None and background.done()
            snapshot = part.manager.snapshot()
            assert snapshot.state is PluginLifecycleState.CLOSED
            assert snapshot.cleanup_status == ("failed" if stage == "close" else "succeeded")
            expected = "CancelledError" if cancel else "ValueError"
            assert (snapshot.cleanup_error if stage == "close" else snapshot.last_error) == expected
            h["report"]["plugin_owned_tasks_remaining"] = 0
            h["report"]["stage"] = stage
            h["report"]["cancel"] = cancel
            assert h["raw"].available and h["session"].is_ready
            # Shared Host close can preserve the original stop error; consume it explicitly.
            if stage == "stop":

                async def already_closed():
                    await part.adapter.close()

                part.close = already_closed

    run(case())


def test_close_during_generation_with_queued_command_and_two_waiters(tmp_path):
    async def case():
        async with harness(tmp_path) as h:
            await started(h)
            part = h["part"]
            plugin = part.manager._plugin
            entered, cleaning, released = asyncio.Event(), asyncio.Event(), asyncio.Event()

            async def handle(command):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaning.set()
                    await released.wait()

            plugin.handle_command = handle
            first = asyncio.create_task(part.host.execute_text("click"))
            await entered.wait()
            queued = asyncio.create_task(part.host.execute_text("click"))
            one = asyncio.create_task(part.host.close())
            two = asyncio.create_task(part.host.close())
            await cleaning.wait()
            one.cancel()
            with pytest.raises(asyncio.CancelledError):
                await one
            assert not two.done() and h["raw"].available
            released.set()
            await two
            with pytest.raises(asyncio.CancelledError):
                await first
            with pytest.raises(LifecycleError):
                await queued
            assert part.manager.snapshot().cleanup_status == "succeeded"
            h["report"]["awaited_plugin_finally"] = True

    run(case())


@pytest.mark.parametrize("stage", ["initialize", "start"])
def test_external_start_cancellation_waits_plugin_cleanup(stage, tmp_path):
    async def case():
        async with harness(tmp_path) as h:
            part = h["part"]
            plugin = part.manager._plugin
            entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

            async def hold(*args):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaning.set()
                    await release.wait()

            setattr(plugin, stage, hold)
            start = asyncio.create_task(part.start())
            await entered.wait()
            start.cancel()
            await cleaning.wait()
            start.cancel()
            assert not start.done()
            close = asyncio.create_task(part.host.close())
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await start
            await close
            assert part.manager.snapshot().last_error == "CancelledError"
            assert part.manager.snapshot().cleanup_status == "succeeded"
            h["report"]["external_cancel_cleanup_waited"] = True

    run(case())


def test_failed_close_does_not_claim_plugin_task_was_released(tmp_path):
    async def case():
        async with harness(tmp_path) as h:
            await started(h)
            part = h["part"]
            background = asyncio.create_task(asyncio.Event().wait(), name="fixture-leaked")

            async def fail():
                raise ValueError("cleanup did not reach owned task")

            part.manager._plugin.close = fail
            try:
                await part.host.close()
                assert part.manager.snapshot().cleanup_status == "failed"
                assert part.manager.snapshot().cleanup_error == "ValueError"
                assert not background.done()
                h["report"]["failed_cleanup_owned_tasks"] = 1
            finally:
                # Fixture owner remediation, not a claim that Manager can kill arbitrary tasks.
                background.cancel()
                await asyncio.gather(background, return_exceptions=True)
                h["report"]["after_fixture_remediation_owned_tasks"] = 0

    run(case())
