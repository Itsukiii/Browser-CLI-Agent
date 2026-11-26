"""Small pure-business contract. No browser/native capabilities are passed to plugins."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from .vision_resources import ResourceSpec
from .vision_types import RecognitionBatch, RecognitionRequest, RecognitionStatus

type Value = str | int | float | bool | None | tuple[Value, ...]


def immutable(value: Value) -> None:
    if type(value) is tuple:
        for item in value:
            immutable(item)
    elif type(value) not in (str, int, float, bool, type(None)):
        raise ValueError("business data must contain only immutable scalar/tuple values")
    elif type(value) is float and not math.isfinite(value):
        raise ValueError("business data must be finite")


@dataclass(frozen=True)
class VisualTarget:
    key: str
    request_key: str
    candidate_index: int = 0

    def __post_init__(self) -> None:
        if (
            type(self.key) is not str
            or not self.key
            or type(self.request_key) is not str
            or not self.request_key
            or type(self.candidate_index) is not int
            or self.candidate_index < 0
        ):
            raise ValueError("invalid immutable visual candidate reference")


@dataclass(frozen=True)
class BusinessState:
    status: RecognitionStatus
    payload: Value
    signature: Value
    interaction_revision: str | None = None
    targets: tuple[VisualTarget, ...] = ()
    diagnostic: str | None = None

    def __post_init__(self) -> None:
        immutable(self.payload)
        immutable(self.signature)
        if not isinstance(self.status, RecognitionStatus):
            raise ValueError("invalid business status")
        if self.interaction_revision is not None and type(self.interaction_revision) is not str:
            raise ValueError("revision must be a string or None")
        if self.diagnostic is not None and type(self.diagnostic) is not str:
            raise ValueError("diagnostic must be a string or None")
        if type(self.targets) is not tuple or any(
            type(t) is not VisualTarget for t in self.targets
        ):
            raise ValueError("targets must be an immutable tuple")
        if len({t.key for t in self.targets}) != len(self.targets):
            raise ValueError("duplicate target keys")


@dataclass(frozen=True)
class ReadIntent:
    query: str = "state"


@dataclass(frozen=True)
class ActionIntent:
    verb: str
    target_key: str
    expected_revision: str
    deadline: float


type Intent = ReadIntent | ActionIntent


class BusinessPlugin(Protocol):
    plugin_id: str
    resources: ResourceSpec

    def plan(self, image_size: tuple[int, int]) -> tuple[RecognitionRequest, ...]: ...
    def observe(self, results: RecognitionBatch) -> BusinessState: ...
    def format_state(self, state: BusinessState) -> str: ...
    def parse_command(self, text: str) -> Intent: ...
    def resolve(self, intent: ActionIntent, current: BusinessState) -> str: ...
    def close(self) -> None: ...
