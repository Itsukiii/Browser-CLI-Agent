"""Serial observation, optional freshness checking, one state commit, bounded notification."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Protocol

from bca.core.errors import LifecycleError, ValidationError
from bca.core.protocol import Event, JsonObject, PageState
from bca.core.protocol.validation import positive

from .diagnostics import ObservationStats, error_code
from .ports import EventSink
from .state_store import StateSnapshot, StateStore, StateStoreClosedError


class FreshnessPolicy(Protocol):
    async def begin(self) -> object: ...

    async def validate(self, token: object, state: PageState) -> bool: ...


class ObservationPipeline:
    """Exclusive publisher for its Store. None freshness does not protect Browser identity."""

    def __init__(
        self,
        observe: Callable[[], Awaitable[PageState]],
        states: StateStore,
        events: EventSink | None = None,
        *,
        freshness: FreshnessPolicy | None = None,
        on_commit: Callable[[object, StateSnapshot], None] | None = None,
        observation_timeout: float = 10.0,
        event_timeout: float = 0.05,
    ) -> None:
        if not callable(observe) or not isinstance(states, StateStore):
            raise ValidationError("observe must be callable and states must be StateStore")
        positive(observation_timeout, "observation_timeout")
        positive(event_timeout, "event_timeout")
        if on_commit is not None and not callable(on_commit):
            raise ValidationError("on_commit must be callable")
        if events is not None and not callable(getattr(events, "emit", None)):
            raise ValidationError("events must provide emit")
        if freshness is not None and not all(
            callable(getattr(freshness, name, None)) for name in ("begin", "validate")
        ):
            raise ValidationError("freshness must provide begin and validate")
        self._observe, self._states, self._events = observe, states, events
        self._freshness = freshness
        self._on_commit = on_commit
        self._observation_timeout, self._event_timeout = observation_timeout, event_timeout
        self._lock = asyncio.Lock()
        self._stats = ObservationStats()

    def snapshot(self) -> ObservationStats:
        return self._stats

    async def _notify(self, kind: str, data: JsonObject) -> None:
        if self._events is None:
            return
        try:
            async with asyncio.timeout(self._event_timeout):
                await self._events.emit(Event(type=kind, source="runtime.observation", data=data))
        except asyncio.CancelledError:
            self._stats = replace(self._stats, event_emit_failed=self._stats.event_emit_failed + 1)
            raise
        except Exception as exc:
            self._stats = replace(
                self._stats,
                event_emit_failed=self._stats.event_emit_failed + 1,
                last_error=error_code(exc),
            )

    async def run_once(self) -> None:
        # Queue wait is outside the observation budget; cancelled waiters own no attempt.
        async with self._lock:
            self._stats = replace(
                self._stats,
                attempts=self._stats.attempts + 1,
                last_observe_duration_ms=0.0,
                last_publish_duration_ms=0.0,
            )
            clock = asyncio.get_running_loop().time
            started = clock()
            observe_finished = False
            publish_started: float | None = None
            kind = "runtime.observation_failed"
            data: JsonObject = {}
            try:
                try:
                    async with asyncio.timeout(self._observation_timeout):
                        if self._states.closed:
                            raise StateStoreClosedError("observation store is closed")
                        token = await self._freshness.begin() if self._freshness else None
                        state = await self._observe()
                        if not isinstance(state, PageState):
                            raise ValidationError("observe must return PageState")
                        valid = (
                            await self._freshness.validate(token, state)
                            if self._freshness
                            else True
                        )
                        if type(valid) is not bool:
                            raise ValidationError("freshness.validate must return bool")
                        self._stats = replace(
                            self._stats, last_observe_duration_ms=(clock() - started) * 1000
                        )
                        observe_finished = True
                        if not valid:
                            self._stats = replace(self._stats, stale=self._stats.stale + 1)
                            kind = "runtime.observation_stale"
                        else:
                            previous = self._states.version
                            publish_started = clock()
                            await self._states.publish(state)
                            self._stats = replace(self._stats, published=self._stats.published + 1)
                            snapshot = self._states.snapshot()
                            if (
                                snapshot is None
                                or snapshot.state is not state
                                or snapshot.version != previous + 1
                            ):
                                raise LifecycleError(
                                    "observation requires exclusive Store publication"
                                )
                            data = {
                                "version": snapshot.version,
                                "plugin_id": state.plugin_id,
                                "source_frame_id": state.source_frame_id,
                            }
                            if self._on_commit is not None:
                                self._on_commit(token, snapshot)
                            kind = "runtime.observation_completed"
                except LifecycleError as exc:
                    self._stats = replace(
                        self._stats, failed=self._stats.failed + 1, last_error=error_code(exc)
                    )
                    raise  # Fatal: Scheduler stops; no repeated structural-error notification.
                except Exception as exc:
                    self._stats = replace(
                        self._stats,
                        failed=self._stats.failed + 1,
                        timed_out=self._stats.timed_out + int(isinstance(exc, TimeoutError)),
                        last_error=error_code(exc),
                    )
                    data = {"error_type": error_code(exc)}
                finally:
                    now = clock()
                    if not observe_finished:
                        self._stats = replace(
                            self._stats, last_observe_duration_ms=(now - started) * 1000
                        )
                    if publish_started is not None:
                        self._stats = replace(
                            self._stats, last_publish_duration_ms=(now - publish_started) * 1000
                        )
                data["observation_duration_ms"] = self._stats.last_observe_duration_ms
                await self._notify(kind, data)
            except asyncio.CancelledError:
                self._stats = replace(
                    self._stats, cancelled=self._stats.cancelled + 1, last_error="CancelledError"
                )
                raise
