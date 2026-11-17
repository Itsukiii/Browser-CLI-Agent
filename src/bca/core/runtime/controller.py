"""Single observation/input channel composition; all external resources are borrowed."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from bca.core.errors import LifecycleError
from bca.core.protocol import PageState
from bca.core.providers import InputProvider

from .action_models import (
    ActionBatch,
    ActionChannelState,
    ActionContextPolicy,
    ActionObservationRef,
    ActionStats,
    BatchResult,
)
from .action_pipeline import ActionPipeline
from .diagnostics import ObservationStats, SchedulerState, SchedulerStats
from .observation import FreshnessPolicy, ObservationPipeline
from .ports import EventSink
from .scheduler import Scheduler
from .state_store import StateSnapshot, StateStore


class RuntimeContext(FreshnessPolicy, ActionContextPolicy, Protocol):
    def commit(self, token: object, snapshot: StateSnapshot) -> None: ...

    def reference(self) -> ActionObservationRef | None: ...


@dataclass(frozen=True, kw_only=True)
class RuntimeSnapshot:
    state: SchedulerState
    action_state: ActionChannelState
    scheduler: SchedulerStats
    observation: ObservationStats
    actions: ActionStats


class RuntimeController:
    def __init__(
        self,
        observe: Callable[[], Awaitable[PageState]],
        provider: InputProvider,
        states: StateStore,
        context: RuntimeContext,
        events: EventSink | None = None,
        *,
        interval: float = 0.1,
        capacity: int = 32,
        observation_timeout: float = 10.0,
        event_timeout: float = 0.05,
    ) -> None:
        self._states, self._context = states, context
        self._gate = asyncio.Lock()
        self._state = SchedulerState.CREATED
        self._lifecycle = asyncio.Lock()
        self._stop_task: asyncio.Task[None] | None = None
        self._observing: asyncio.Task[object] | None = None
        self.observation = ObservationPipeline(
            observe,
            states,
            events,
            freshness=context,
            on_commit=context.commit,
            observation_timeout=observation_timeout,
            event_timeout=event_timeout,
        )
        self.scheduler = Scheduler(self._observe, interval=interval)
        self.actions = ActionPipeline(
            provider,
            context,
            events,
            capacity=capacity,
            gate=self._gate,
            request_refresh=self.scheduler.request_immediate,
            event_timeout=event_timeout,
        )

    @property
    def state(self) -> SchedulerState:
        return self._state

    def reference(self) -> ActionObservationRef | None:
        return self._context.reference()

    def snapshot(self) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            state=self._state,
            action_state=self.actions.state,
            scheduler=self.scheduler.snapshot(),
            observation=self.observation.snapshot(),
            actions=self.actions.snapshot(),
        )

    def _external(self) -> None:
        if asyncio.current_task() is self._observing:
            raise LifecycleError("observation cannot await its own controller")
        self.actions._external()

    def _live(self) -> None:
        if self._state not in (SchedulerState.RUNNING, SchedulerState.PAUSED):
            raise LifecycleError("controller is not running")

    async def _observe(self) -> None:
        async with self._gate:
            if self._state is SchedulerState.RUNNING:
                self._observing = asyncio.current_task()
                try:
                    await self.observation.run_once()
                finally:
                    self._observing = None

    async def start(self) -> None:
        async with self._lifecycle:
            if self._state is SchedulerState.RUNNING:
                return
            if self._state is not SchedulerState.CREATED:
                raise LifecycleError("controller cannot restart")
            try:
                if self._states.closed:
                    raise LifecycleError("state store is closed")
                await self.actions.start()
                self._state = SchedulerState.RUNNING
                await self.scheduler.start()
            except BaseException:
                await self.stop()
                raise

    async def pause(self) -> None:
        self._external()
        async with self._lifecycle:
            self._live()
            await self.scheduler.pause()
            self._live()  # stop wins even while waiting for observation completion
            self._state = SchedulerState.PAUSED

    async def resume(self) -> None:
        self._external()
        async with self._lifecycle:
            self._live()
            await self.scheduler.resume()
            self._live()
            self._state = SchedulerState.RUNNING

    async def submit(self, batch: ActionBatch) -> BatchResult:
        self._external()
        self._live()
        return await self.actions.submit(batch)

    async def recover(self, provider: InputProvider, reference: ActionObservationRef) -> None:
        self._external()
        self._live()
        await self.actions.recover(provider, reference)

    async def stop(self) -> None:
        self._external()
        if self._stop_task is None:
            self._state = SchedulerState.STOPPING
            self.actions.inhibit()
            self._stop_task = asyncio.create_task(self._stop())
        await asyncio.shield(self._stop_task)

    async def _stop(self) -> None:
        await asyncio.gather(self.scheduler.stop(), self.actions.stop())
        self._state = SchedulerState.STOPPED
