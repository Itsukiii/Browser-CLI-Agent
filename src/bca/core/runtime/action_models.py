"""Runtime-local batch contracts; deliberately outside Protocol 2 codecs."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from bca.core.errors import ValidationError
from bca.core.protocol import Action, ActionResult
from bca.core.providers import InputProvider


@dataclass(frozen=True, kw_only=True)
class ActionObservationRef:
    version: int
    token: object = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version <= 0:
            raise ValidationError("version must be a positive integer")


@dataclass(frozen=True, kw_only=True)
class ActionBatch:
    actions: tuple[Action, ...]
    observation: ActionObservationRef | None = None
    request_id: str | None = None
    batch_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not isinstance(self.actions, tuple) or any(
            not isinstance(action, Action) for action in self.actions
        ):
            raise ValidationError("actions must be a tuple of Action")
        if len({a.action_id for a in self.actions}) != len(self.actions):
            raise ValidationError("duplicate action IDs")
        if len({a.page_id for a in self.actions}) > 1:
            raise ValidationError("mixed page IDs")
        if self.observation is not None and not isinstance(self.observation, ActionObservationRef):
            raise ValidationError("invalid observation reference")
        for value in (self.batch_id, self.request_id):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValidationError("IDs must be nonempty strings")
        if self.batch_id is None:
            raise ValidationError("batch_id is required")


class BatchStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STALE = "stale"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class ActionChannelState(StrEnum):
    CREATED = "created"
    READY = "ready"
    BLOCKED = "blocked"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass(frozen=True, kw_only=True)
class BatchResult:
    batch_id: str
    request_id: str | None
    status: BatchStatus
    results: tuple[ActionResult, ...]
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime
    failed_index: int | None = None
    error_type: str | None = None


@dataclass(frozen=True, kw_only=True)
class ActionStats:
    accepted: int = 0
    executed: int = 0
    completed: int = 0
    failed: int = 0
    stale: int = 0
    cancelled: int = 0
    blocked: int = 0
    pending: int = 0
    full_waits: int = 0
    first_error_stops: int = 0
    uncertain: int = 0
    event_emit_failed: int = 0
    last_capacity_wait_ms: float = 0
    last_queue_wait_ms: float = 0
    last_execution_ms: float = 0
    last_error: str | None = None


class ActionContextPolicy(Protocol):
    async def check(self, reference: ActionObservationRef | None, action: Action) -> bool: ...

    async def allow_recovery(
        self,
        previous: InputProvider,
        replacement: InputProvider,
        reference: ActionObservationRef,
        blocked_reference: ActionObservationRef | None,
    ) -> bool: ...
