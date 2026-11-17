"""One operation at a time, fixed-rate epochs, skipped ticks and coalesced requests."""

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import replace

from bca.core.errors import LifecycleError, ValidationError
from bca.core.protocol.validation import positive

from .diagnostics import SchedulerState, SchedulerStats, error_code


class Scheduler:
    def __init__(self, operation: Callable[[], Awaitable[None]], *, interval: float = 0.1) -> None:
        if not callable(operation):
            raise ValidationError("operation must be callable")
        positive(interval, "interval")
        self._operation, self._interval = operation, interval
        self._state = SchedulerState.CREATED
        self._stats = SchedulerStats()
        self._pending = False
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._lifecycle = asyncio.Lock()
        self._worker: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[None] | None = None
        self._anchor = 0.0
        self._tick = 0

    @property
    def state(self) -> SchedulerState:
        return self._state

    def snapshot(self) -> SchedulerStats:
        return self._stats

    def _now(self) -> float:
        return asyncio.get_running_loop().time()

    def _check_live(self) -> None:
        if self._state in (SchedulerState.STOPPING, SchedulerState.STOPPED):
            raise LifecycleError("scheduler is stopped")

    def _check_external(self) -> None:
        if asyncio.current_task() is self._worker:
            raise LifecycleError("operation cannot await its own scheduler lifecycle")

    async def start(self) -> None:
        self._check_external()
        async with self._lifecycle:
            self._check_live()
            if self._state is SchedulerState.RUNNING:
                return
            if self._state is SchedulerState.PAUSED:
                raise LifecycleError("use resume for a paused scheduler")
            self._anchor, self._tick = self._now(), 0
            self._state = SchedulerState.RUNNING
            self._worker = asyncio.create_task(self._run(), name="bca-scheduler")

    def request_immediate(self) -> None:
        self._check_live()
        if self._pending:
            self._stats = replace(
                self._stats, coalesced_requests=self._stats.coalesced_requests + 1
            )
        self._pending = True
        self._wake.set()

    async def pause(self) -> None:
        self._check_external()
        async with self._lifecycle:
            if self._state is SchedulerState.CREATED:
                raise LifecycleError("start before pause")
            if self._state in (SchedulerState.STOPPING, SchedulerState.STOPPED):
                await self.stop()
                return
            self._state = SchedulerState.PAUSED
            self._wake.set()
            await self._idle.wait()
            if self._state is SchedulerState.STOPPING:
                await self.stop()

    async def resume(self) -> None:
        self._check_external()
        async with self._lifecycle:
            self._check_live()
            if self._state is SchedulerState.RUNNING:
                return
            if self._state is SchedulerState.CREATED:
                raise LifecycleError("start before resume")
            await self._idle.wait()  # A cancelled pause waiter must not allow overlapping work.
            self._check_live()
            self._anchor, self._tick = self._now(), 0
            self._state = SchedulerState.RUNNING
            self._wake.set()

    async def stop(self) -> None:
        self._check_external()
        if self._stop_task is None:
            self._state = SchedulerState.STOPPING
            self._pending = False
            self._wake.set()
            self._stop_task = asyncio.create_task(self._stop(), name="bca-scheduler-stop")
        await asyncio.shield(self._stop_task)

    async def _stop(self) -> None:
        try:
            if self._worker is not None:
                self._worker.cancel()
                try:
                    await self._worker
                except asyncio.CancelledError:
                    pass
        finally:
            self._state = SchedulerState.STOPPED
            self._idle.set()
            self._wake.set()

    async def _wait(self, delay: float | None) -> None:
        try:
            async with asyncio.timeout(delay):
                await self._wake.wait()
        except TimeoutError:
            pass

    def _skip_past_ticks(self) -> None:
        # Near-equality tolerance only compensates floating-point division at exact ticks.
        elapsed_ticks = (self._now() - self._anchor) / self._interval
        missed = max(0, math.ceil(elapsed_ticks - self._tick - 1e-9))
        self._tick += missed
        self._stats = replace(self._stats, skipped_ticks=self._stats.skipped_ticks + missed)

    async def _run(self) -> None:
        try:
            while self._state not in (SchedulerState.STOPPING, SchedulerState.STOPPED):
                self._wake.clear()
                if self._state is SchedulerState.PAUSED:
                    await self._wait(None)
                    continue
                deadline = self._anchor + self._tick * self._interval
                due = self._now() >= deadline
                if not due and not self._pending:
                    await self._wait(max(0, deadline - self._now()))
                    continue
                self._pending = False
                if due:
                    self._tick += 1
                self._idle.clear()
                started = self._now()
                self._stats = replace(
                    self._stats,
                    started=self._stats.started + 1,
                    periodic_runs=self._stats.periodic_runs + int(due),
                    immediate_runs=self._stats.immediate_runs + int(not due),
                )
                try:
                    await self._operation()
                    self._stats = replace(self._stats, completed=self._stats.completed + 1)
                except asyncio.CancelledError:
                    self._stats = replace(self._stats, cancelled=self._stats.cancelled + 1)
                    raise
                except Exception as exc:
                    self._stats = replace(
                        self._stats, failed=self._stats.failed + 1, last_error=error_code(exc)
                    )
                    if isinstance(exc, LifecycleError):
                        return
                finally:
                    self._stats = replace(
                        self._stats, last_run_duration_ms=(self._now() - started) * 1000
                    )
                    self._idle.set()
                self._skip_past_ticks()
                await asyncio.sleep(0)  # Fairness even for synchronously completing callbacks.
        except Exception as exc:
            self._stats = replace(self._stats, last_error=error_code(exc))
        finally:
            self._state = SchedulerState.STOPPED
            self._idle.set()
            self._wake.set()
