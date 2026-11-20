"""One activation: command generation and input coordinated with Runtime observation."""

import asyncio

from bca.core.errors import LifecycleError
from bca.core.runtime import (
    ActionBatch,
    BatchResult,
    RuntimeController,
    SchedulerState,
    StateSnapshot,
    StateStore,
)

from .manager import PluginManager, settle
from .models import PluginLifecycleState


class PluginRuntimeHost:
    def __init__(
        self, manager: PluginManager, controller: RuntimeController, states: StateStore
    ) -> None:
        if controller.state is not SchedulerState.CREATED:
            raise LifecycleError("host requires an unstarted controller")
        self._manager, self._controller, self._states = manager, controller, states
        self._commands = asyncio.Lock()
        self._running = self._closing = False
        self._start_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._command: asyncio.Task[BatchResult] | None = None
        self._cancel_sent = False

    def _external(self) -> None:
        self._manager._external()
        self._controller.actions._external()
        if asyncio.current_task() is self._command:
            raise LifecycleError("command callback cannot await its own host")

    def _live(self) -> None:
        if self._closing or not self._running:
            raise LifecycleError("host is not accepting commands")
        if self._manager.snapshot().state is not PluginLifecycleState.RUNNING:
            raise LifecycleError("plugin is not active")
        if self._controller.state not in (SchedulerState.RUNNING, SchedulerState.PAUSED):
            raise LifecycleError("runtime is not active")

    async def start(self) -> None:
        self._external()
        if self._closing:
            raise LifecycleError("closed host cannot restart")
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name="bca.plugin.host.start")
        try:
            await asyncio.shield(self._start_task)
        except BaseException:
            if self._close_task is None:
                self._begin_close()
            assert self._close_task is not None
            try:
                await settle(self._close_task)
            except Exception:
                pass  # Manager retains cleanup diagnostics; preserve the startup failure.
            raise

    async def _start(self) -> None:
        await self._manager.initialize()
        if self._closing:
            raise LifecycleError("host closed during initialization")
        await self._manager.start()
        if self._closing:
            raise LifecycleError("host closed during startup")
        await self._controller.start()
        if not self._closing:
            self._running = True

    async def execute_text(self, text: str, *, source: str = "cli") -> BatchResult:
        self._external()
        self._live()
        async with self._commands:
            self._live()
            task = asyncio.create_task(self._execute(text, source), name="bca.plugin.command")
            self._command = task
            self._cancel_sent = False
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                self._cancel_command()
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not task.cancelled():
                    task.exception()
                raise
            finally:
                self._command = None
                self._cancel_sent = False

    async def _execute(self, text: str, source: str) -> BatchResult:
        paused_here = self._controller.state is SchedulerState.RUNNING
        primary_error = False
        try:
            if paused_here:
                await self._controller.pause()
            self._live()
            # Exact pairing before any plugin await; never replace this ref later.
            snapshot, reference = self._states.snapshot(), self._controller.reference()
            if (
                snapshot is None
                or reference is None
                or snapshot.version != reference.version
                or snapshot.state.plugin_id != self._manager.snapshot().plugin_id
            ):
                raise LifecycleError(
                    "command requires a committed observation of the active plugin"
                )
            command = self._manager.parse_command(text, source=source)
            actions = await self._manager.handle_command(command)
            self._live()
            return await self._controller.submit(
                ActionBatch(actions=actions, observation=reference, request_id=command.request_id)
            )
        except BaseException:
            primary_error = True
            raise
        finally:
            if (
                paused_here
                and not self._closing
                and self._controller.state in (SchedulerState.RUNNING, SchedulerState.PAUSED)
            ):
                try:
                    await self._controller.resume()
                except Exception:
                    if not primary_error:
                        raise

    def snapshot(self) -> StateSnapshot | None:
        return self._states.snapshot()

    def format_current_state(self) -> str | None:
        self._live()
        value = self.snapshot()
        return self._manager.format_state(value.state) if value is not None else None

    def _cancel_command(self) -> None:
        if self._command is not None and not self._cancel_sent:
            self._cancel_sent = True
            self._command.cancel()

    def _begin_close(self) -> None:
        self._closing = True
        self._running = False
        self._close_task = asyncio.create_task(self._close(), name="bca.plugin.host.close")

    async def close(self) -> None:
        self._external()
        if self._close_task is None:
            self._begin_close()
        assert self._close_task is not None
        await asyncio.shield(self._close_task)

    async def _close(self) -> None:
        try:
            await self._controller.stop()
        finally:
            self._cancel_command()
            if self._command is not None:
                await asyncio.gather(self._command, return_exceptions=True)
            if self._start_task is not None and not self._start_task.done():
                self._start_task.cancel()
                await asyncio.gather(self._start_task, return_exceptions=True)
            try:
                await self._manager.stop()
            finally:
                await self._manager.close()
