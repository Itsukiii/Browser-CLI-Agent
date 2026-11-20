"""Explicit Browser assembly recipe; caller owns session, raw providers and sinks.

03.2 tests this contract with real CDP; plugin_integration.py is the executable campaign.
Use policy.create_input_provider() before this function to retain recovery provenance.
The caller must load/navigate its owned page and start all raw providers first.
"""

import logging
from collections.abc import Sequence
from pathlib import Path

from bca.core.browser import BrowserSession
from bca.core.plugins import (
    FreshnessCaptureAdapter,
    PluginCatalog,
    PluginConfig,
    PluginManager,
    PluginRuntimeHost,
    ProviderLookupView,
)
from bca.core.providers import CaptureProvider, InputProvider, ProviderRegistry
from bca.core.runtime import BrowserFreshness, EventBus, RuntimeController, StateStore


async def assemble(
    session: BrowserSession,
    raw_capture: CaptureProvider,
    inputs: InputProvider,
    states: StateStore,
    events: EventBus,
    policy: BrowserFreshness,
    roots: Sequence[Path],
) -> tuple[PluginRuntimeHost, FreshnessCaptureAdapter]:
    """Return unstarted host and started adapter; caller closes both before raw resources."""
    adapter = FreshnessCaptureAdapter(session, raw_capture, policy)
    await adapter.start()
    manager: PluginManager | None = None
    try:
        registry = ProviderRegistry()
        registry.register(raw_capture)
        registry.register(inputs)
        view = ProviderLookupView(registry, overrides={"capture": adapter, "input": inputs})
        catalog = PluginCatalog(roots)
        catalog.discover()
        manager = PluginManager(
            catalog,
            providers=view,
            states=states,
            events=events,
            logger=logging.getLogger("bca.plugin.example"),
        )
        manager.load("example", config=PluginConfig(values={"page_id": session.page_id}))
        controller = RuntimeController(manager.observe, inputs, states, policy, events)
        return PluginRuntimeHost(manager, controller, states), adapter
    except BaseException:
        if manager is not None:
            await manager.close()
        await adapter.close()
        raise
