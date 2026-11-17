"""Immutable, payload-free runtime diagnostics; counters persist for object lifetime."""

from dataclasses import dataclass
from enum import StrEnum


class SchedulerState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass(frozen=True, kw_only=True)
class SchedulerStats:
    started: int = 0
    completed: int = 0
    periodic_runs: int = 0
    immediate_runs: int = 0
    skipped_ticks: int = 0
    coalesced_requests: int = 0
    failed: int = 0
    cancelled: int = 0
    last_run_duration_ms: float = 0.0
    last_error: str | None = None


@dataclass(frozen=True, kw_only=True)
class ObservationStats:
    attempts: int = 0
    published: int = 0
    stale: int = 0
    failed: int = 0
    timed_out: int = 0
    cancelled: int = 0
    event_emit_failed: int = 0
    last_observe_duration_ms: float = 0.0
    last_publish_duration_ms: float = 0.0
    last_error: str | None = None


def error_code(error: BaseException) -> str:
    # Never include exception messages, plugin payloads or input text.
    return type(error).__name__
