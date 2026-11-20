import asyncio
import logging

import pytest

from bca.core.browser import BrowserCaptureProvider, BrowserSession
from bca.core.errors import (
    CapabilityTypeError,
    CapabilityUnavailableError,
    CommandError,
    LifecycleError,
    ValidationError,
)
from bca.core.plugins import (
    FreshnessCaptureAdapter,
    PluginCatalog,
    PluginConfig,
    PluginManager,
    PluginRuntimeHost,
    ProviderLookupView,
)
from bca.core.protocol import PageState
from bca.core.providers import CaptureProvider, InputProvider, ProviderRegistry
from bca.core.runtime import (
    BatchStatus,
    BrowserFreshness,
    EventBus,
    RuntimeController,
    SchedulerState,
    StateStore,
)

from ..browser.test_input import InputPeer
from ..runtime.action_fakes import Input, until
from .test_manager import ROOT, FakePlugin, Loader, bounded


async def assembly(peer, plugin=None, input_override=None):
    session = BrowserSession(peer.endpoint)
    await session.connect()
    await session.bind("page-a")
    states, bus = StateStore(), EventBus()
    policy = BrowserFreshness(session, states)
    raw = BrowserCaptureProvider(session)
    await raw.start()
    inputs = input_override or policy.create_input_provider()
    await inputs.start()
    adapter = FreshnessCaptureAdapter(session, raw, policy)
    await adapter.start()
    registry = ProviderRegistry()
    registry.register(raw)
    registry.register(inputs)
    view = ProviderLookupView(registry, overrides={"capture": adapter, "input": inputs})
    catalog = PluginCatalog([ROOT / "plugins"])
    catalog.discover()
    manager = PluginManager(
        catalog,
        providers=view,
        states=states,
        events=bus,
        logger=logging.getLogger("test"),
        loader=Loader(plugin) if plugin else None,
    )
    manager.load("example", config=PluginConfig(values={"page_id": "page-a"}))
    controller = RuntimeController(manager.observe, inputs, states, policy, bus, interval=100)
    host = PluginRuntimeHost(manager, controller, states)
    return host, manager, controller, states, policy, view, adapter, raw, inputs, session, bus


async def cleanup(parts):
    host, manager, controller, states, policy, view, adapter, raw, inputs, session, bus = parts
    await host.close()
    await adapter.close()
    await inputs.close()
    await raw.close()
    await session.close()
    await states.close()
    await bus.close()
    assert not session.connection.reader_running and session.connection.pending_count == 0


def test_full_mock_cdp_source_single_publish_and_command_ids():
    async def run():
        async with InputPeer() as peer:
            parts = await assembly(peer)
            host, manager, c, states, policy, view, adapter, raw, inputs, session, bus = parts
            try:
                assert view.get("capture") is view.get(CaptureProvider) is adapter
                assert view.get("input") is view.get(InputProvider) is inputs
                await host.start()
                await states.wait_for_update(0)
                await c.pause()
                assert states.version == 1 and states.snapshot().state.source_frame_id
                assert (
                    len([r for r in peer.requests if r["method"] == "Page.captureScreenshot"]) == 1
                )
                ref = c.reference()
                result = await host.execute_text("click 12 23")
                assert result.status is BatchStatus.SUCCEEDED
                assert result.request_id and result.results[0].action_id
                assert c.reference() is ref and c.state is SchedulerState.PAUSED
                assert states.version == 1 and host.format_current_state().startswith("example")
                await host.close()
                await host.close()
                assert raw.available and inputs.available and session.is_ready
                assert not states.closed and not bus.closed
            finally:
                await cleanup(parts)

    asyncio.run(bounded(run()))


def test_stale_keeps_original_reference_and_no_replay():
    from plugins.example import ExamplePlugin

    async def run():
        class Changing(ExamplePlugin):
            async def handle_command(self, command):
                actions = await super().handle_command(command)
                await states.publish(PageState(plugin_id="example", sequence=99))
                return actions

        async with InputPeer() as peer:
            parts = await assembly(peer, Changing())
            host, _, c, states, *_ = parts
            try:
                await host.start()
                await states.wait_for_update(0)
                await c.pause()
                result = await host.execute_text("click 12 23")
                assert result.status is BatchStatus.STALE and not peer.inputs
            finally:
                await cleanup(parts)

    asyncio.run(bounded(run()))


def test_concurrent_commands_and_resume_after_parse_failure():
    async def run():
        async with InputPeer() as peer:
            parts = await assembly(peer)
            host, _, c, states, *_ = parts
            try:
                await host.start()
                await states.wait_for_update(0)
                with pytest.raises(CommandError):
                    await host.execute_text("private invalid")
                assert c.state is SchedulerState.RUNNING
                results = await asyncio.gather(
                    *(host.execute_text(f"click {x} 20") for x in range(10, 15))
                )
                assert all(r.status is BatchStatus.SUCCEEDED for r in results)
                presses = [
                    r["params"]["x"] for r in peer.inputs if r["params"]["type"] == "mousePressed"
                ]
                assert presses == list(range(10, 15))
            finally:
                await cleanup(parts)

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("where", ["handle", "input", "pause"])
def test_cancel_and_close_wait_for_cleanup(where):
    from plugins.example import ExamplePlugin

    async def run():
        entered, release, cleaning = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Held(ExamplePlugin):
            async def handle_command(self, command):
                if where == "handle":
                    entered.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cleaning.set()
                        await release.wait()
                return await super().handle_command(command)

        fake = Input() if where == "input" else None
        if fake:
            fake.gate.clear()
            fake.cleanup.clear()
        async with InputPeer() as peer:
            parts = await assembly(peer, Held(), fake)
            host, _, c, states, *_ = parts
            try:
                await host.start()
                await states.wait_for_update(0)
                if where == "pause":
                    peer.gate.clear()
                    c.scheduler.request_immediate()
                    await until(
                        lambda: (
                            len(
                                [
                                    r
                                    for r in peer.requests
                                    if r["method"] == "Page.captureScreenshot"
                                ]
                            )
                            == 2
                        )
                    )
                task = asyncio.create_task(host.execute_text("click 12 23"))
                if where == "handle":
                    await entered.wait()
                elif where == "input":
                    await fake.entered.wait()
                else:
                    await until(lambda: c.scheduler.state is SchedulerState.PAUSED)
                task.cancel()
                if where == "pause":
                    peer.gate.set()
                elif where == "handle":
                    await cleaning.wait()
                else:
                    await fake.cleaning.wait()
                task.cancel()
                if where != "pause":
                    closing = asyncio.create_task(host.close())
                    await asyncio.sleep(0)
                    assert not task.done()
                    release.set()
                    if fake:
                        fake.cleanup.set()
                    await closing
                with pytest.raises(asyncio.CancelledError):
                    await task
                if where == "pause":
                    assert c.state is SchedulerState.RUNNING
            finally:
                peer.gate.set()
                release.set()
                if fake:
                    fake.cleanup.set()
                await cleanup(parts)

    asyncio.run(bounded(run()))


def test_missing_trusted_observation_rejected():
    async def run():
        async with InputPeer() as peer:
            parts = await assembly(peer, FakePlugin())
            host, _, c, states, *_ = parts
            try:
                await host.start()
                await c.pause()
                assert states.version == 0
                with pytest.raises(LifecycleError):
                    await host.execute_text("noop")
                assert not peer.inputs
            finally:
                await cleanup(parts)

    asyncio.run(bounded(run()))


def test_view_and_adapter_error_boundaries():
    async def run():
        async with InputPeer() as peer:
            parts = await assembly(peer)
            host, m, c, states, policy, view, adapter, raw, inputs, s, b = parts
            try:
                with pytest.raises(CapabilityTypeError):
                    view.get(BrowserCaptureProvider)
                with pytest.raises(ValidationError):
                    view.available(42)
                with pytest.raises(ValidationError):
                    await adapter.capture("other")
                with pytest.raises(LifecycleError):
                    await adapter.capture("page-a")
                with pytest.raises(ValidationError):
                    FreshnessCaptureAdapter(s, adapter, policy)
                await adapter.close()
                assert not view.available("capture") and raw.available and s.is_ready
                with pytest.raises(CapabilityUnavailableError):
                    view.get("capture")
                with pytest.raises(LifecycleError):
                    await adapter.start()
            finally:
                await cleanup(parts)

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("mode", ["failed", "blocked", "cancelled_result"])
def test_host_preserves_runtime_results(mode):
    async def run():
        fake = Input()
        fake.failure_at = 1
        if mode == "blocked":
            fake.after = lambda: setattr(fake, "input_state_uncertain", True)
        if mode == "cancelled_result":
            from dataclasses import replace

            from bca.core.protocol import ActionStatus

            original = fake.execute

            async def execute(a):
                return replace(await original(a), status=ActionStatus.CANCELLED)

            fake.execute = execute
        async with InputPeer() as peer:
            parts = await assembly(peer, input_override=fake)
            host, _, c, states, *_ = parts
            try:
                await host.start()
                await states.wait_for_update(0)
                await c.pause()
                result = await host.execute_text("click 12 23")
                assert result.status is BatchStatus.FAILED
                assert len(result.results) == 1 and len(fake.calls) == 1
                if mode != "failed":
                    assert c.actions.state.value == "blocked"
            finally:
                await cleanup(parts)

    asyncio.run(bounded(run()))


def test_host_start_failure_and_close_during_initialize():
    async def run():
        async with InputPeer() as peer:
            plugin = FakePlugin("initialize")
            parts = await assembly(peer, plugin)
            host = parts[0]
            try:
                task = asyncio.create_task(host.start())
                await plugin.entered.wait()
                await host.close()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert parts[1].snapshot().state.value == "closed"
                with pytest.raises(LifecycleError):
                    await host.start()
            finally:
                await cleanup(parts)

    asyncio.run(bounded(run()))


def test_cancel_waiting_command_does_not_cancel_active():
    async def run():
        fake = Input()
        fake.gate.clear()
        async with InputPeer() as peer:
            parts = await assembly(peer, input_override=fake)
            host, _, c, states, *_ = parts
            try:
                await host.start()
                await states.wait_for_update(0)
                await c.pause()
                first = asyncio.create_task(host.execute_text("click 12 23"))
                await fake.entered.wait()
                second = asyncio.create_task(host.execute_text("click 20 23"))
                await asyncio.sleep(0)
                second.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await second
                fake.gate.set()
                assert (await first).status is BatchStatus.SUCCEEDED and len(fake.calls) == 1
            finally:
                fake.gate.set()
                await cleanup(parts)

    asyncio.run(bounded(run()))


def test_browser_recipe_uses_actual_provider_and_borrowed_resources():
    from examples.plugin_browser import assemble

    async def run():
        async with InputPeer() as peer:
            session = BrowserSession(peer.endpoint)
            await session.connect()
            await session.bind("page-a")
            states, bus = StateStore(), EventBus()
            policy = BrowserFreshness(session, states)
            raw = BrowserCaptureProvider(session)
            await raw.start()
            inputs = policy.create_input_provider()
            await inputs.start()
            host, adapter = await assemble(
                session, raw, inputs, states, bus, policy, [ROOT / "plugins"]
            )
            try:
                await host.start()
                await states.wait_for_update(0)
                assert (await host.execute_text("click 12 23")).status is BatchStatus.SUCCEEDED
                await host.close()
                await adapter.close()
                assert raw.available and inputs.available and session.is_ready
            finally:
                await host.close()
                await adapter.close()
                await inputs.close()
                await raw.close()
                await session.close()
                await states.close()
                await bus.close()

    asyncio.run(bounded(run()))


def test_empty_command_batch_and_closed_host_rejection():
    from plugins.example import ExamplePlugin

    class Empty(ExamplePlugin):
        async def handle_command(self, command):
            return ()

    async def run():
        baseline = asyncio.all_tasks()
        async with InputPeer() as peer:
            parts = await assembly(peer, Empty())
            host, _, c, states, *_ = parts
            try:
                await host.start()
                await states.wait_for_update(0)
                result = await host.execute_text("click 12 23")
                assert (
                    result.status is BatchStatus.SUCCEEDED
                    and not result.results
                    and not peer.inputs
                )
                await host.close()
                with pytest.raises(LifecycleError):
                    await host.execute_text("click 12 23")
            finally:
                await cleanup(parts)
        assert not asyncio.all_tasks() - baseline

    asyncio.run(bounded(run()))
