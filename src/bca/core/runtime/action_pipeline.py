"""Bounded FIFO batches with cancellation completion barriers and borrowed input."""

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from bca.core.errors import LifecycleError, ValidationError
from bca.core.protocol import ActionResult, ActionStatus, Event
from bca.core.protocol.validation import positive
from bca.core.providers import InputProvider

from .action_models import (
    ActionBatch,
    ActionChannelState,
    ActionContextPolicy,
    ActionObservationRef,
    ActionStats,
    BatchResult,
    BatchStatus,
)
from .ports import EventSink


@dataclass(eq=False)
class _Entry:
    batch: ActionBatch
    future: asyncio.Future[BatchResult]
    queued: float
    queued_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    results: list[ActionResult] = field(default_factory=list)
    task: asyncio.Task[BatchResult] | None = None
    inflight: bool = False
    cancel_requested: bool = False

    def cancel(self) -> None:
        if self.task is not None and not self.cancel_requested:
            self.cancel_requested = True
            self.task.cancel()


async def _settle(future: asyncio.Future[BatchResult]) -> None:
    # Repeated caller cancellation must not interrupt provider release/cleanup.
    while not future.done():
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError:
            continue


class ActionPipeline:
    def __init__(
        self,
        provider: InputProvider,
        context: ActionContextPolicy,
        events: EventSink | None = None,
        *,
        capacity: int = 32,
        gate: asyncio.Lock | None = None,
        request_refresh: Callable[[], None] | None = None,
        event_timeout: float = 0.05,
    ) -> None:
        if type(capacity) is not int or capacity <= 0:
            raise ValidationError("capacity must be a positive integer")
        positive(event_timeout, "event_timeout")
        self._provider, self._context, self._events = provider, context, events
        self._capacity, self._gate = capacity, gate if gate is not None else asyncio.Lock()
        self._request_refresh, self._event_timeout = request_refresh, event_timeout
        self._state = ActionChannelState.CREATED
        self._queue: deque[_Entry] = deque()
        self._admission = asyncio.Lock()
        self._changed = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[None] | None = None
        self._active: _Entry | None = None
        self._stats = ActionStats()
        self._blocked_reference: ActionObservationRef | None = None

    @property
    def state(self) -> ActionChannelState:
        return self._state

    def snapshot(self) -> ActionStats:
        return replace(self._stats, pending=len(self._queue))

    async def start(self) -> None:
        if self._state is ActionChannelState.READY:
            return
        if self._state is not ActionChannelState.CREATED:
            raise LifecycleError("action pipeline cannot restart")
        if not self._provider.available or self._uncertain():
            raise LifecycleError("input provider is not ready")
        self._state = ActionChannelState.READY
        self._worker = asyncio.create_task(self._run(), name="bca.actions")

    def _uncertain(self) -> bool:
        return bool(getattr(self._provider, "input_state_uncertain", False))

    def _ready(self) -> None:
        if self._state is not ActionChannelState.READY:
            raise LifecycleError("action channel is not ready")

    def _external(self) -> None:
        if self._active is not None and asyncio.current_task() is self._active.task:
            raise LifecycleError("input callback cannot await its own action channel")

    async def submit(self, batch: ActionBatch) -> BatchResult:
        self._external()
        if not isinstance(batch, ActionBatch):
            raise ValidationError("batch must be ActionBatch")
        self._ready()
        clock = asyncio.get_running_loop().time
        began = clock()
        async with self._admission:
            self._ready()
            if len(self._queue) >= self._capacity:
                self._stats = replace(self._stats, full_waits=self._stats.full_waits + 1)
            while len(self._queue) >= self._capacity:
                self._changed.clear()
                await self._changed.wait()
                self._ready()
            # No await between final readiness check and queue commitment.
            self._ready()
            entry = _Entry(batch, asyncio.get_running_loop().create_future(), clock())
            self._queue.append(entry)
            self._stats = replace(
                self._stats,
                accepted=self._stats.accepted + 1,
                last_capacity_wait_ms=(clock() - began) * 1000,
            )
            self._changed.set()
        try:
            return await asyncio.shield(entry.future)
        except asyncio.CancelledError:
            if entry in self._queue:
                self._queue.remove(entry)
                self._finish(entry, self._result(entry, BatchStatus.CANCELLED))
                self._changed.set()
            elif not entry.future.done():
                if entry.task is not None:
                    entry.cancel()
                await _settle(entry.future)
            raise

    def _result(
        self,
        entry: _Entry,
        status: BatchStatus,
        index: int | None = None,
        error: str | None = None,
    ) -> BatchResult:
        return BatchResult(
            batch_id=entry.batch.batch_id,
            request_id=entry.batch.request_id,
            status=status,
            results=tuple(entry.results),
            failed_index=index,
            error_type=error,
            queued_at=entry.queued_at,
            started_at=entry.started_at,
            finished_at=datetime.now(UTC),
        )

    def _finish(self, entry: _Entry, result: BatchResult) -> None:
        if entry.future.done():
            return
        field_name = {
            BatchStatus.SUCCEEDED: "completed",
            BatchStatus.FAILED: "failed",
            BatchStatus.STALE: "stale",
            BatchStatus.CANCELLED: "cancelled",
            BatchStatus.BLOCKED: "blocked",
        }[result.status]
        self._stats = replace(
            self._stats,
            **{field_name: getattr(self._stats, field_name) + 1},
            last_error=result.error_type or self._stats.last_error,
        )
        entry.future.set_result(result)

    def _drain(self, status: BatchStatus) -> None:
        while self._queue:
            entry = self._queue.popleft()
            self._finish(entry, self._result(entry, status))
        self._changed.set()

    def _block(self, entry: _Entry, *, uncertain: bool = False) -> None:
        if self._state is ActionChannelState.READY:
            self._state = ActionChannelState.BLOCKED
            self._blocked_reference = entry.batch.observation
        if uncertain:
            self._stats = replace(self._stats, uncertain=self._stats.uncertain + 1)
        self._drain(BatchStatus.BLOCKED)

    def _refresh(self) -> None:
        if self._request_refresh is not None:
            try:
                self._request_refresh()
            except Exception as exc:
                self._stats = replace(self._stats, last_error=type(exc).__name__)

    async def _process(self, entry: _Entry) -> BatchResult:
        index: int | None = None
        try:
            async with self._gate:
                if self._state is not ActionChannelState.READY:
                    return self._result(entry, BatchStatus.CANCELLED)
                for index, action in enumerate(entry.batch.actions):
                    if not self._provider.available or self._uncertain():
                        self._block(entry, uncertain=self._uncertain())
                        return self._result(entry, BatchStatus.BLOCKED, index, "InputUnavailable")
                    valid = await self._context.check(entry.batch.observation, action)
                    if type(valid) is not bool:
                        raise TypeError("context.check must return bool")
                    if not valid:
                        return self._result(entry, BatchStatus.STALE, index, "StaleObservation")
                    entry.inflight = True
                    result = await self._provider.execute(action)
                    entry.inflight = False
                    if isinstance(result, ActionResult):
                        entry.results.append(result)
                    if not isinstance(result, ActionResult) or result.action_id != action.action_id:
                        self._block(entry, uncertain=True)
                        return self._result(entry, BatchStatus.FAILED, index, "InvalidActionResult")
                    if result.status is not ActionStatus.SUCCEEDED:
                        self._stats = replace(
                            self._stats,
                            first_error_stops=self._stats.first_error_stops + 1,
                        )
                        if (
                            self._uncertain()
                            or not self._provider.available
                            or result.status is ActionStatus.CANCELLED
                            or not await self._context.check(entry.batch.observation, action)
                        ):
                            self._block(
                                entry,
                                uncertain=self._uncertain()
                                or result.status is ActionStatus.CANCELLED,
                            )
                        return self._result(entry, BatchStatus.FAILED, index, "ActionFailed")
                    if self._uncertain():
                        self._block(entry, uncertain=True)
                        return self._result(entry, BatchStatus.BLOCKED, index, "InputUncertain")
                return self._result(entry, BatchStatus.SUCCEEDED)
        except asyncio.CancelledError:
            if entry.inflight or entry.results or self._uncertain():
                self._block(entry, uncertain=True)
            return self._result(entry, BatchStatus.CANCELLED, index, "CancelledError")
        except ValidationError:
            return self._result(entry, BatchStatus.FAILED, index, "ValidationError")
        except Exception as exc:
            self._block(entry, uncertain=entry.inflight or self._uncertain())
            return self._result(entry, BatchStatus.FAILED, index, type(exc).__name__)

    async def _notify(self, result: BatchResult) -> None:
        if self._events is None:
            return
        kind = "completed" if result.status is BatchStatus.SUCCEEDED else result.status.value
        try:
            async with asyncio.timeout(self._event_timeout):
                await self._events.emit(
                    Event(
                        type="runtime.action_" + kind,
                        source="runtime.actions",
                        request_id=result.request_id,
                        data={
                            "batch_id": result.batch_id,
                            "error_type": result.error_type,
                            "action_ids": [r.action_id for r in result.results],
                            "duration_ms": self._stats.last_execution_ms,
                        },
                    )
                )
        except (Exception, asyncio.CancelledError):
            self._stats = replace(self._stats, event_emit_failed=self._stats.event_emit_failed + 1)

    async def _run(self) -> None:
        while self._state not in (ActionChannelState.STOPPING, ActionChannelState.STOPPED):
            if not self._queue:
                self._changed.clear()
                await self._changed.wait()
                continue
            entry = self._queue.popleft()
            self._active = entry
            started = asyncio.get_running_loop().time()
            entry.started_at = datetime.now(UTC)
            self._stats = replace(
                self._stats,
                executed=self._stats.executed + 1,
                last_queue_wait_ms=(started - entry.queued) * 1000,
            )
            entry.task = asyncio.create_task(self._process(entry), name="bca.action.batch")
            self._changed.set()
            try:
                result = await entry.task
            except asyncio.CancelledError:  # cancelled before coroutine's first instruction
                result = self._result(entry, BatchStatus.CANCELLED, error="CancelledError")
            self._stats = replace(
                self._stats,
                last_execution_ms=(asyncio.get_running_loop().time() - started) * 1000,
            )
            self._finish(entry, result)
            self._active = None
            self._refresh()
            await self._notify(result)

    def inhibit(self) -> None:
        """Synchronous stop linearization point, also used by Controller."""
        if self._state is not ActionChannelState.STOPPED:
            self._state = ActionChannelState.STOPPING
            self._drain(BatchStatus.CANCELLED)

    async def stop(self) -> None:
        self._external()
        if self._stop_task is None:
            self.inhibit()
            self._stop_task = asyncio.create_task(self._stop())
        await asyncio.shield(self._stop_task)

    async def _stop(self) -> None:
        if self._active is not None and self._active.task is not None:
            self._active.cancel()
        self._changed.set()
        if self._worker is not None:
            await self._worker
        self._state = ActionChannelState.STOPPED

    async def recover(self, replacement: InputProvider, reference: ActionObservationRef) -> None:
        self._external()
        async with self._gate:
            if self._state is not ActionChannelState.BLOCKED or self._active is not None:
                raise LifecycleError("recovery requires an idle blocked channel")
            if (
                replacement is self._provider
                or not replacement.available
                or bool(getattr(replacement, "input_state_uncertain", False))
                or not await self._context.allow_recovery(
                    self._provider, replacement, reference, self._blocked_reference
                )
            ):
                raise LifecycleError("external known-state recovery has not been verified")
            if self._state is not ActionChannelState.BLOCKED:
                raise LifecycleError("channel stopped during recovery")
            self._provider = replacement
            self._state = ActionChannelState.READY
            self._blocked_reference = None
            self._changed.set()
