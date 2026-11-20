"""One plugin instance, serialized calls and cancellation-safe owned cleanup."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from logging import Logger
from typing import TypeVar

from bca.core.errors import LifecycleError
from bca.core.protocol import Action, Command, PageState
from bca.core.providers import ProviderLookup
from bca.core.runtime import EventSink, StateSink

from .catalog import PluginCatalog
from .contracts import Plugin, PluginConfig, PluginContext
from .errors import PluginContractError
from .loader import PluginLoader
from .models import PluginLifecycleState as S
from .models import PluginSnapshot
from .validation import validate_capabilities

T = TypeVar("T")


async def settle(task: asyncio.Task[None]) -> None:
    """Wait through repeated caller cancellation; do not cancel owned cleanup."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    task.result()


class PluginManager:
    def __init__(
        self,
        catalog: PluginCatalog,
        *,
        providers: ProviderLookup,
        states: StateSink,
        events: EventSink,
        logger: Logger,
        loader: PluginLoader | None = None,
    ) -> None:
        self._catalog, self._loader = catalog, loader or PluginLoader()
        self._providers, self._states, self._events, self._logger = (
            providers,
            states,
            events,
            logger,
        )
        self._plugin: Plugin | None = None
        self._context: PluginContext | None = None
        self._state = S.CREATED
        self._last_error: str | None = None
        self._cleanup_status = "not_started"
        self._cleanup_error: str | None = None
        self._lock = asyncio.Lock()
        self._active: asyncio.Task[object] | None = None
        self._cancel_sent = False
        self._stop_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._initialized = False

    def snapshot(self) -> PluginSnapshot:
        metadata = self._plugin.metadata if self._plugin is not None else None
        return PluginSnapshot(
            plugin_id=metadata.plugin_id if metadata else None,
            version=metadata.version if metadata else None,
            state=self._state,
            required_capabilities=metadata.required_capabilities if metadata else (),
            last_error=self._last_error,
            cleanup_status=self._cleanup_status,
            cleanup_error=self._cleanup_error,
        )

    def load(self, plugin_id: str, *, config: PluginConfig | None = None) -> None:
        if self._state is not S.CREATED:
            raise LifecycleError("manager already selected a plugin or is closed")
        if config is not None and not isinstance(config, PluginConfig):
            raise PluginContractError("config must be PluginConfig")
        try:
            plugin = self._loader.load(self._catalog.get(plugin_id))
            self._plugin = plugin
            self._context = PluginContext(
                self._providers,
                self._states,
                self._events,
                self._logger,
                config if config is not None else PluginConfig(),
            )
            self._state = S.LOADED
        except Exception as exc:
            self._last_error = type(exc).__name__
            raise

    def _external(self) -> None:
        if asyncio.current_task() is self._active:
            raise LifecycleError("plugin callback cannot await its own manager")

    def _require(self, *states: S) -> Plugin:
        if self._state not in states or self._plugin is None:
            raise LifecycleError("plugin lifecycle does not allow this operation")
        return self._plugin

    def _cancel_active(self) -> None:
        if self._active is not None and not self._cancel_sent:
            self._cancel_sent = True
            self._active.cancel()

    async def _invoke(self, call: Callable[[], Awaitable[T]]) -> T:
        async def run() -> T:
            return await call()

        task = asyncio.create_task(run(), name="bca.plugin.call")
        self._active = task
        self._cancel_sent = False
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            self._cancel_active()
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not task.cancelled():
                task.exception()  # retrieve cleanup failures without replacing caller cancellation
            raise
        finally:
            self._active = None
            self._cancel_sent = False

    @staticmethod
    def _none(value: object) -> None:
        if value is not None:
            if inspect.iscoroutine(value):
                value.close()
            raise PluginContractError("plugin lifecycle method must return None")

    async def _cleanup(self) -> None:
        self._cleanup_status = "running"
        try:
            if self._plugin is not None:
                self._none(await self._invoke(self._plugin.close))
            self._cleanup_status = "succeeded"
        except BaseException as exc:
            self._cleanup_status = "failed"
            self._cleanup_error = type(exc).__name__
            # Cleanup is diagnostic: callers keep their original failure/cancellation.

    async def _ensure_cleanup(self) -> None:
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup(), name="bca.plugin.cleanup")
        await settle(self._cleanup_task)

    async def initialize(self) -> None:
        self._external()
        async with self._lock:
            if self._initialized and self._state in (S.INITIALIZED, S.RUNNING, S.STOPPED):
                return
            plugin = self._require(S.LOADED)
            self._state = S.INITIALIZING
            try:
                validate_capabilities(plugin.metadata, self._providers)
                context = self._context
                assert context is not None
                self._none(await self._invoke(lambda: plugin.initialize(context)))
                if self._state is S.INITIALIZING:
                    self._initialized = True
                    self._state = S.INITIALIZED
            except BaseException as exc:
                self._last_error = type(exc).__name__
                if self._state not in (S.CLOSING, S.STOPPING):
                    self._state = S.FAILED
                await self._ensure_cleanup()
                raise

    async def start(self) -> None:
        self._external()
        async with self._lock:
            if self._state is S.RUNNING:
                return
            plugin = self._require(S.INITIALIZED, S.STOPPED)
            if not self._initialized or self._cleanup_task is not None:
                raise LifecycleError("plugin cannot restart after failed cleanup")
            self._stop_task = None
            self._state = S.STARTING
            try:
                self._none(await self._invoke(plugin.start))
                if self._state is S.STARTING:
                    self._state = S.RUNNING
            except BaseException as exc:
                self._last_error = type(exc).__name__
                if self._state not in (S.CLOSING, S.STOPPING):
                    self._state = S.FAILED
                await self._ensure_cleanup()
                raise

    async def stop(self) -> None:
        self._external()
        if self._close_task is not None:
            await asyncio.shield(self._close_task)
            return
        if self._state in (S.CREATED, S.LOADED, S.INITIALIZED, S.STOPPED, S.FAILED, S.CLOSED):
            return
        if self._stop_task is None:
            self._state = S.STOPPING
            self._cancel_active()
            self._stop_task = asyncio.create_task(self._stop(), name="bca.plugin.stop")
        await asyncio.shield(self._stop_task)

    async def _stop(self) -> None:
        async with self._lock:
            try:
                if self._plugin is not None and self._cleanup_task is None:
                    self._none(await self._invoke(self._plugin.stop))
                if self._state is not S.CLOSING:
                    self._state = S.STOPPED if self._cleanup_task is None else S.FAILED
            except BaseException as exc:
                self._last_error = type(exc).__name__
                if self._state is not S.CLOSING:
                    self._state = S.FAILED
                await self._ensure_cleanup()
                raise

    async def close(self) -> None:
        self._external()
        if self._close_task is None:
            self._state = S.CLOSING
            # Do not cancel an already running stop or cleanup callback a second time.
            if self._stop_task is None and self._cleanup_task is None:
                self._cancel_active()
            self._close_task = asyncio.create_task(self._close(), name="bca.plugin.close")
        await asyncio.shield(self._close_task)

    async def _close(self) -> None:
        if self._stop_task is not None:
            await asyncio.gather(self._stop_task, return_exceptions=True)
        async with self._lock:
            await self._ensure_cleanup()
            self._state = S.CLOSED

    async def observe(self) -> PageState:
        self._external()
        async with self._lock:
            plugin = self._require(S.RUNNING)
            try:
                value = await self._invoke(plugin.observe)
                if not isinstance(value, PageState) or value.plugin_id != plugin.metadata.plugin_id:
                    if inspect.iscoroutine(value):
                        value.close()
                    raise PluginContractError("observe must return this plugin's PageState")
                return value
            except BaseException as exc:
                self._last_error = type(exc).__name__
                raise

    async def handle_command(self, command: Command) -> tuple[Action, ...]:
        self._external()
        async with self._lock:
            plugin = self._require(S.RUNNING)
            try:
                if not isinstance(command, Command):
                    raise PluginContractError("command must be Command")
                value = await self._invoke(lambda: plugin.handle_command(command))
                if not isinstance(value, tuple) or any(not isinstance(a, Action) for a in value):
                    if inspect.iscoroutine(value):
                        value.close()
                    raise PluginContractError("handle_command must return tuple[Action, ...]")
                return value
            except BaseException as exc:
                self._last_error = type(exc).__name__
                raise

    def parse_command(self, text: str, *, source: str = "cli") -> Command:
        plugin = self._require(S.RUNNING)
        try:
            value = plugin.parse_command(text, source=source)
            if not isinstance(value, Command):
                if inspect.iscoroutine(value):
                    value.close()
                raise PluginContractError("parse_command must return Command")
            return value
        except Exception as exc:
            self._last_error = type(exc).__name__
            raise

    def format_state(self, state: PageState) -> str:
        plugin = self._require(S.RUNNING)
        try:
            if not isinstance(state, PageState) or state.plugin_id != plugin.metadata.plugin_id:
                raise PluginContractError("state belongs to a different plugin")
            value = plugin.format_state(state)
            if not isinstance(value, str):
                if inspect.iscoroutine(value):
                    value.close()
                raise PluginContractError("format_state must return str")
            return value
        except Exception as exc:
            self._last_error = type(exc).__name__
            raise
