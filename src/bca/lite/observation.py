"""One application gate for observation, pure business parsing and one-step commands."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, replace

from .bridge import ObservationRef
from .plugin import ActionIntent, BusinessPlugin, BusinessState, Intent, ReadIntent
from .vision import MaaVisionFacade
from .vision_types import Box, CloseReport, RecognitionBatch, RecognitionStatus, VisionError


@dataclass(frozen=True)
class VisualObservation:
    sequence: int
    state: BusinessState
    source: ObservationRef | None
    binding: tuple[str | None, str | None, int] | None
    image_size: tuple[int, int] | None
    completed_at: float
    expired: bool
    regions: tuple[tuple[str, Box], ...] = ()
    coordinate_space: str = "maa_image_pixels"


@dataclass(frozen=True)
class Change:
    sequence: int
    status: RecognitionStatus


@dataclass(frozen=True)
class CommandResult:
    outcome: str
    observation: VisualObservation
    text: str


@dataclass(frozen=True)
class ObservationStats:
    completed: int
    valid: int
    dropped_notifications: int
    skipped_ticks: int
    last_duration: float


class ObservationCoordinator:
    """Exclusive owner of facade/plugin. Application closes providers only after released=True.

    stop drains and pauses; start resumes. Cancellation retires and closes the
    composition. A new coordinator/bridge is required after retirement or close.
    Notifications are bounded sequence-only hints; latest is the current snapshot.
    """

    def __init__(
        self,
        facade: MaaVisionFacade,
        plugin: BusinessPlugin,
        *,
        interval: float = 1.0,
        notification_capacity: int = 16,
    ) -> None:
        if not math.isfinite(interval) or interval <= 0 or notification_capacity < 1:
            raise ValueError("positive interval/capacity required")
        if facade.resources != plugin.resources:
            raise ValueError("plugin and facade resource ownership must agree")
        self._loop = asyncio.get_running_loop()
        self._facade, self._plugin = facade, plugin
        self._gate = asyncio.Lock()
        self._interval = interval
        self._wake = asyncio.Event()
        self._running = False
        self._closing = False
        self._retired = False
        self._plugin_closed = False
        self._periodic: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[CloseReport] | None = None
        self._notifications: asyncio.Queue[Change] = asyncio.Queue(notification_capacity)
        self.latest: VisualObservation | None = None
        self._completed = self._valid = self._dropped = self._skipped = 0
        self._duration = 0.0
        self._epoch = 0

    @property
    def stats(self) -> ObservationStats:
        return ObservationStats(
            self._completed, self._valid, self._dropped, self._skipped, self._duration
        )

    def take_change(self) -> Change | None:
        try:
            return self._notifications.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def _owner(self) -> None:
        if asyncio.get_running_loop() is not self._loop:
            raise VisionError("coordinator requires owner loop")

    def _check(self) -> None:
        if self._closing or self._retired or not self._running:
            raise VisionError("coordinator is stopped, closed or retired")

    async def start(self) -> None:
        self._owner()
        try:
            async with self._gate:
                if self._closing or self._retired:
                    raise VisionError("coordinator cannot restart after close/retirement")
                if self._running:
                    return
                epoch = self._epoch
                await self._facade.start()
                if self._closing or epoch != self._epoch:
                    return  # A concurrent stop/close wins over unfinished startup.
                self._running = True
                self._epoch += 1
                self._wake.clear()
                self._periodic = asyncio.create_task(self._observe_loop(self._epoch))
        except asyncio.CancelledError:
            await self._cancel_cleanup()
            raise
        except Exception:
            await self.aclose()
            raise

    async def _observe_loop(self, epoch: int) -> None:
        # First periodic capture occurs after one interval; explicit refresh is immediate.
        delay = self._interval
        while self._running and not self._closing and not self._retired and epoch == self._epoch:
            try:
                await asyncio.wait_for(self._wake.wait(), delay)
                return
            except TimeoutError:
                pass
            started = time.monotonic()
            async with self._gate:
                if not self._running or self._closing or self._retired or epoch != self._epoch:
                    return
                await self._refresh_locked()
            elapsed = time.monotonic() - started
            self._skipped += int(elapsed // self._interval)
            delay = max(0.001, self._interval - elapsed)

    def _publish(self, state: BusinessState, batch: RecognitionBatch | None) -> VisualObservation:
        self._completed += 1
        valid = batch is not None and batch.source_current
        observation = VisualObservation(
            self._completed,
            state,
            batch.capture.source_ref if batch is not None and valid else None,
            batch.capture.binding if batch is not None and valid else None,
            (batch.capture.width, batch.capture.height) if batch is not None and valid else None,
            time.monotonic(),
            batch.expired if batch else True,
            tuple((r.request_key, c.box) for r in batch.results for c in r.candidates)
            if batch is not None and valid
            else (),
        )
        old = self.latest
        self.latest = observation
        if state.status == RecognitionStatus.MATCHED and valid and not observation.expired:
            self._valid += 1
        signature = (state.status, state.signature, state.diagnostic)
        if old is None or signature != (
            old.state.status,
            old.state.signature,
            old.state.diagnostic,
        ):
            if self._notifications.full():
                self._notifications.get_nowait()
                self._dropped += 1
            self._notifications.put_nowait(Change(observation.sequence, state.status))
        return observation

    async def _refresh_locked(self) -> tuple[VisualObservation, RecognitionBatch | None]:
        started = time.monotonic()
        batch = None
        try:
            batch = await self._facade.recognize(self._plugin.plan)
            state = self._plugin.observe(batch)
            if not batch.source_current or any(
                r.status == RecognitionStatus.ERROR for r in batch.results
            ):
                state = BusinessState(
                    RecognitionStatus.ERROR, None, None, diagnostic="recognition_error"
                )
            if not isinstance(state, BusinessState):
                raise ValueError("plugin must return BusinessState")
        except Exception as exc:
            state = BusinessState(
                RecognitionStatus.ERROR, None, None, diagnostic=type(exc).__name__
            )
        if not self._facade.connected:
            self._retired = True
            self._wake.set()
        result = self._publish(state, batch)
        self._duration = time.monotonic() - started
        return result, batch

    async def refresh(self) -> VisualObservation:
        self._owner()
        try:
            async with self._gate:
                self._check()
                result, _ = await self._refresh_locked()
                return result
        except asyncio.CancelledError:
            await self._cancel_cleanup()
            raise

    async def execute_text(self, text: str) -> CommandResult:
        self._owner()
        return await self.execute_intent(self._plugin.parse_command(text))

    async def execute_intent(self, intent: Intent) -> CommandResult:
        self._owner()
        try:
            async with self._gate:
                self._check()
                before, batch = await self._refresh_locked()
                if isinstance(intent, ReadIntent):
                    return CommandResult("read", before, self._plugin.format_state(before.state))
                self._check()
                if not isinstance(intent, ActionIntent) or intent.verb != "click":
                    raise VisionError("unsupported action")
                if (
                    not math.isfinite(intent.deadline)
                    or time.monotonic() >= intent.deadline
                    or not intent.expected_revision
                    or before.state.interaction_revision != intent.expected_revision
                    or before.state.status != RecognitionStatus.MATCHED
                    or batch is None
                    or batch.expired
                    or not batch.source_current
                ):
                    raise VisionError("intent expired, revision changed or observation invalid")
                key = self._plugin.resolve(intent, before.state)
                targets = [t for t in before.state.targets if t.key == key == intent.target_key]
                if len(targets) != 1:
                    raise VisionError("plugin did not resolve the requested unique target")
                # Recheck synchronous plugin work against the deadline before native input.
                if time.monotonic() >= intent.deadline:
                    raise VisionError("intent expired during resolution")
                target = targets[0]
                outcome = await self._facade.click(
                    batch, target.request_key, target.candidate_index
                )
                if outcome == "unknown" or not self._facade.connected:
                    self._retired = True
                    self._wake.set()
                    error = self._publish(
                        BusinessState(
                            RecognitionStatus.ERROR, None, None, diagnostic="input_unknown"
                        ),
                        None,
                    )
                    return CommandResult(outcome, error, self._plugin.format_state(error.state))
                after, _ = await self._refresh_locked()
                return CommandResult(outcome, after, self._plugin.format_state(after.state))
        except asyncio.CancelledError:
            await self._cancel_cleanup()
            raise

    async def stop(self) -> None:
        self._owner()
        self._running = False
        self._epoch += 1
        periodic = self._periodic
        self._wake.set()
        try:
            async with self._gate:
                pass
            if periodic:
                await asyncio.shield(periodic)
        except asyncio.CancelledError:
            await self._cancel_cleanup()
            raise

    async def _cancel_cleanup(self) -> None:
        self._retired = True
        self._facade.invalidate()
        await self.aclose()

    async def _close(self) -> CloseReport:
        self._running = False
        self._wake.set()
        async with self._gate:
            report = await self._facade.aclose()
            if not self._plugin_closed:
                try:
                    self._plugin.close()
                    self._plugin_closed = True
                except Exception as exc:
                    report = replace(report, errors=report.errors + (f"plugin close: {exc}",))
        if self._periodic:
            await self._periodic
        return report

    async def aclose(self) -> CloseReport:
        self._owner()
        self._closing = True
        if self._close_task is not None and self._close_task.done():
            if not self._close_task.result().released or not self._plugin_closed:
                self._close_task = None
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        cancelled = False
        while not self._close_task.done():
            try:
                await asyncio.shield(self._close_task)
            except asyncio.CancelledError:
                cancelled = True
                self._facade.invalidate()
        report = self._close_task.result()
        if cancelled:
            raise asyncio.CancelledError
        return report
