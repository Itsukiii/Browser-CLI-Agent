import asyncio
import logging
from pathlib import Path

import pytest

from bca.core.errors import CapabilityNotFoundError, LifecycleError
from bca.core.plugins import (
    PluginCatalog,
    PluginContractError,
    PluginManager,
)
from bca.core.plugins import (
    PluginLifecycleState as S,
)
from bca.core.protocol import Command, PageState
from bca.core.providers import ProviderRegistry
from bca.core.runtime import EventBus, StateStore
from plugins.example import ExamplePlugin

ROOT = Path(__file__).resolve().parents[3]


class FakePlugin(ExamplePlugin):
    def __init__(self, stage=None, failure=None):
        super().__init__()
        self.stage, self.failure = stage, failure
        self.entered, self.release, self.cleaning = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        self.cleanup_release = asyncio.Event()
        self.cleanup_release.set()
        self.calls = []
        self.close_error = False
        self.bad = None

    async def step(self, stage):
        self.calls.append(stage)
        if self.stage == stage:
            self.entered.set()
            if self.failure:
                raise self.failure
            try:
                await self.release.wait()
            finally:
                self.cleaning.set()
                await self.cleanup_release.wait()

    async def initialize(self, context):
        await self.step("initialize")
        self._context = context

    async def start(self):
        await self.step("start")

    async def observe(self):
        await self.step("observe")
        return PageState(plugin_id="wrong" if self.bad == "observe" else "example", sequence=1)

    async def handle_command(self, command):
        await self.step("handle")
        return [] if self.bad == "handle" else ()

    def parse_command(self, text, *, source="cli"):
        return object() if self.bad == "parse" else Command(name="noop", source=source)

    def format_state(self, state):
        return None if self.bad == "format" else "formatted"

    async def stop(self):
        await self.step("stop")

    async def close(self):
        await self.step("close")
        if self.close_error:
            raise RuntimeError("private cleanup")


class Loader:
    def __init__(self, plugin):
        self.plugin = plugin

    def load(self, descriptor):
        return self.plugin


def manager(plugin, providers=None):
    from ...plugin_sdk.test_example import FakeCapture
    from ..runtime.action_fakes import Input

    registry = ProviderRegistry()
    if providers is None:
        capture = FakeCapture(None)
        # Existing fake readiness is started below by callers if needed.
        registry.register(capture)
        registry.register(Input())
    catalog = PluginCatalog([ROOT / "plugins"])
    catalog.discover()
    value = PluginManager(
        catalog,
        providers=providers or registry,
        states=StateStore(),
        events=EventBus(),
        logger=logging.getLogger("test"),
        loader=Loader(plugin),
    )
    value.load("example")
    return value, registry


async def ready(plugin):
    value, registry = manager(plugin)
    for p in registry._providers.values():
        await p.start()
    return value, registry


async def bounded(coro):
    async with asyncio.timeout(4):
        return await coro


def test_lifecycle_restart_and_no_shared_close():
    async def run():
        p = FakePlugin()
        m, r = await ready(p)
        await m.initialize()
        await m.initialize()
        await m.start()
        await m.start()
        assert (await m.observe()).plugin_id == "example"
        await m.stop()
        await m.stop()
        await m.start()
        await m.close()
        await m.close()
        assert p.calls == ["initialize", "start", "observe", "stop", "start", "close"]
        assert m.snapshot().state is S.CLOSED and m.snapshot().cleanup_status == "succeeded"
        assert all(p.available for p in r._providers.values())
        with pytest.raises(LifecycleError):
            await m.start()

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("stage", ["initialize", "start"])
@pytest.mark.parametrize("cancel", [False, True])
def test_startup_failure_cleanup_keeps_primary_error(stage, cancel):
    async def run():
        p = FakePlugin(stage, None if cancel else ValueError("private"))
        p.close_error = True
        m, _ = await ready(p)
        if stage == "start":
            await m.initialize()
        task = asyncio.create_task(getattr(m, stage)())
        await p.entered.wait()
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else ValueError):
            await task
        assert m.snapshot().state is S.FAILED
        assert m.snapshot().cleanup_error == "RuntimeError"
        assert m.snapshot().last_error == ("CancelledError" if cancel else "ValueError")
        await m.close()
        assert p.calls.count("close") == 1

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("stage", ["observe", "handle"])
def test_close_cancels_and_awaits_work_once(stage):
    async def run():
        p = FakePlugin(stage)
        m, _ = await ready(p)
        await m.initialize()
        await m.start()
        p.cleanup_release.clear()
        call = m.observe() if stage == "observe" else m.handle_command(Command(name="noop"))
        work = asyncio.create_task(call)
        await p.entered.wait()
        closing = asyncio.create_task(m.close())
        await p.cleaning.wait()
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        other = asyncio.create_task(m.close())
        await asyncio.sleep(0)
        assert not other.done()
        p.cleanup_release.set()
        await other
        with pytest.raises(asyncio.CancelledError):
            await work
        assert p.calls.count("close") == 1 and m.snapshot().state is S.CLOSED

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("bad", ["observe", "handle", "parse", "format"])
def test_call_boundary_types(bad):
    async def run():
        p = FakePlugin()
        m, _ = await ready(p)
        await m.initialize()
        await m.start()
        p.bad = bad
        with pytest.raises(PluginContractError):
            if bad == "observe":
                await m.observe()
            elif bad == "handle":
                await m.handle_command(Command(name="noop"))
            elif bad == "parse":
                m.parse_command("secret")
            else:
                m.format_state(PageState(plugin_id="example", sequence=1))
        assert m.snapshot().last_error == "PluginContractError"
        await m.close()

    asyncio.run(bounded(run()))


def test_capability_category_preserved():
    async def run():
        m, _ = manager(FakePlugin(), ProviderRegistry())
        with pytest.raises(CapabilityNotFoundError) as error:
            await m.initialize()
        assert "example" in str(error.value)
        assert m.snapshot().cleanup_status == "succeeded"
        await m.close()

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("stage", ["initialize", "start", "stop", "close"])
def test_close_competes_with_lifecycle_and_cancelled_waiter(stage):
    async def run():
        p = FakePlugin(stage)
        m, _ = await ready(p)
        if stage != "initialize":
            await m.initialize()
        if stage in ("stop", "close"):
            await m.start()
        work = asyncio.create_task(getattr(m, stage)())
        await p.entered.wait()
        closing = asyncio.create_task(m.close())
        await asyncio.sleep(0)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        p.release.set()
        await m.close()
        await asyncio.gather(work, return_exceptions=True)
        assert m.snapshot().state is S.CLOSED
        assert p.calls.count("close") == 1

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("kind", ["unready", "type"])
def test_capability_distinctions(kind):
    from bca.core.errors import CapabilityTypeError, CapabilityUnavailableError
    from bca.core.providers import Provider

    class Wrong(Provider):
        capability = "capture"

        @property
        def available(self):
            return True

        async def start(self):
            pass

        async def close(self):
            pass

    async def run():
        p = FakePlugin()
        m, registry = manager(p)
        if kind == "type":
            registry._providers["capture"] = Wrong()
        with pytest.raises(CapabilityTypeError if kind == "type" else CapabilityUnavailableError):
            await m.initialize()
        assert not p.calls or p.calls == ["close"]
        await m.close()

    asyncio.run(bounded(run()))


def test_lifecycle_return_contract_and_stop_failure():
    async def run():
        class Bad(FakePlugin):
            async def start(self):
                return 1

        m, _ = await ready(Bad())
        await m.initialize()
        with pytest.raises(PluginContractError):
            await m.start()
        assert m.snapshot().cleanup_status == "succeeded"
        await m.close()
        p = FakePlugin("stop", ValueError("secret"))
        m, _ = await ready(p)
        await m.initialize()
        await m.start()
        with pytest.raises(ValueError):
            await m.stop()
        await m.close()
        assert m.snapshot().last_error == "ValueError" and p.calls.count("close") == 1

    asyncio.run(bounded(run()))


def test_repeated_call_cancellation_waits_for_plugin_cleanup():
    async def run():
        p = FakePlugin("observe")
        m, _ = await ready(p)
        await m.initialize()
        await m.start()
        p.cleanup_release.clear()
        task = asyncio.create_task(m.observe())
        await p.entered.wait()
        task.cancel()
        await p.cleaning.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        p.cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await m.close()

    asyncio.run(bounded(run()))


def test_default_configs_are_independent():
    async def run():
        a, b = FakePlugin(), FakePlugin()
        ma, _ = await ready(a)
        mb, _ = await ready(b)
        await ma.initialize()
        await mb.initialize()
        assert a._context.config is not b._context.config
        assert a._context.config.values is not b._context.config.values
        await ma.close()
        await mb.close()

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("method", ["observe", "handle_command"])
def test_async_method_returning_nested_coroutine_is_rejected_without_leak(method):
    async def run():
        p = FakePlugin()

        async def nested():
            return None

        async def wrong(*args):
            return nested()

        setattr(p, method, wrong)
        m, _ = await ready(p)
        await m.initialize()
        await m.start()
        with pytest.raises(PluginContractError):
            if method == "observe":
                await m.observe()
            else:
                await m.handle_command(Command(name="noop"))
        await m.close()

    asyncio.run(bounded(run()))
