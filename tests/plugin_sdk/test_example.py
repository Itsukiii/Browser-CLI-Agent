import asyncio
import logging

import pytest

from bca.core.errors import CapabilityUnavailableError, CommandError, LifecycleError
from bca.core.plugins import PluginConfig, PluginContext
from bca.core.protocol import ActionResult, ActionStatus, Command, Event
from bca.core.protocol.models import utc_now
from bca.core.providers import InputProvider, ProviderRegistry
from bca.plugin_sdk.interfaces import Plugin
from tests.core.test_providers import FakeCapture


class FakeInput(InputProvider):
    def __init__(self):
        self.ready = False
        self.executed = []

    @property
    def available(self):
        return self.ready

    async def start(self):
        self.ready = True

    async def close(self):
        self.ready = False

    async def execute(self, action):
        if not self.ready:
            raise CapabilityUnavailableError("input not started")
        self.executed.append(action)
        now = utc_now()
        return ActionResult(
            action_id=action.action_id,
            status=ActionStatus.SUCCEEDED,
            started_at=now,
            finished_at=now,
        )


class Sink:
    def __init__(self):
        self.states = []
        self.events = []

    async def publish(self, state):
        self.states.append(state)

    async def emit(self, event):
        self.events.append(event)


def test_plugin_flow(frame, example_class):
    async def scenario():
        registry = ProviderRegistry()
        capture, inputs = FakeCapture(frame), FakeInput()
        sink = Sink()
        context = PluginContext(
            registry,
            sink,
            sink,
            logging.getLogger("bca.plugins.example"),
            PluginConfig(values={"page_id": "demo"}),
        )
        plugin: Plugin = example_class()
        with pytest.raises(LifecycleError):
            await plugin.start()
        with pytest.raises(CapabilityUnavailableError):
            await plugin.initialize(context)
        for provider in (capture, inputs):
            registry.register(provider)
            await provider.start()
        await plugin.initialize(context)
        with pytest.raises(LifecycleError):
            await plugin.initialize(context)
        await plugin.start()
        state = await plugin.observe()
        await context.states.publish(state)
        assert state.source_frame_id == frame.frame_id
        assert state.data["width"] == 2
        assert "example #1" in plugin.format_state(state)
        assert (await plugin.observe()).sequence == 2
        command = plugin.parse_command("click 12 23")
        actions = await plugin.handle_command(command)
        assert inputs.executed == []  # Plugin maps; Core executes.
        for action in actions:
            result = await registry.get(InputProvider).execute(action)
            assert result.action_id == action.action_id
            assert action.request_id == command.request_id
        await context.events.emit(Event(type="example.ready", source="example"))
        assert len(sink.states) == len(sink.events) == 1
        for text in ("bad", "click -1 0", "click nan 2", "click x y"):
            with pytest.raises(CommandError):
                plugin.parse_command(text)
        with pytest.raises(CommandError):
            await plugin.handle_command(Command(name="bad"))
        await plugin.stop()
        await plugin.stop()
        with pytest.raises(LifecycleError):
            await plugin.observe()
        await plugin.start()
        await plugin.close()
        await plugin.close()
        with pytest.raises(LifecycleError):
            await plugin.start()
        assert inputs.available  # Plugin must not close shared Core providers.
        await inputs.close()
        await capture.close()

    asyncio.run(scenario())
