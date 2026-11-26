"""Pure fixture business logic: template button plus optional visible OCR round number."""

from __future__ import annotations

import time

from bca.lite.plugin import ActionIntent, BusinessState, Intent, ReadIntent, VisualTarget
from bca.lite.vision_resources import ResourceSpec
from bca.lite.vision_types import (
    OCRRequest,
    RecognitionBatch,
    RecognitionRequest,
    RecognitionStatus,
    TemplateRequest,
)


class FixturePlugin:
    plugin_id = "lite-fixture"

    def __init__(self, resources: ResourceSpec) -> None:
        self.resources = resources

    def plan(self, image_size: tuple[int, int]) -> tuple[RecognitionRequest, ...]:
        requests: tuple[RecognitionRequest, ...] = (TemplateRequest("button", "marker.png"),)
        if self.resources.ocr is not None:
            requests += (OCRRequest("round"),)
        return requests

    def observe(self, results: RecognitionBatch) -> BusinessState:
        button = results.results[0]
        status = button.status
        revision = None
        if self.resources.ocr is not None:
            number = results.results[1]
            if number.status != RecognitionStatus.MATCHED:
                status = number.status
            elif len(number.candidates) == 1:
                revision = number.candidates[0].text
        targets = (VisualTarget("button", "button"),) if status == RecognitionStatus.MATCHED else ()
        payload = (status.value, revision)
        return BusinessState(status, payload, payload, revision, targets)

    def format_state(self, state: BusinessState) -> str:
        return f"{state.status}: {state.payload}"

    def parse_command(self, text: str) -> Intent:
        parts = text.split()
        if parts == ["?"]:
            return ReadIntent()
        if len(parts) == 2 and parts[0] == "click":
            return ActionIntent("click", "button", parts[1], time.monotonic() + 5)
        raise ValueError("expected '?' or 'click <visible-round>'")

    def resolve(self, intent: ActionIntent, current: BusinessState) -> str:
        if intent.target_key != "button":
            raise ValueError("unknown fixture target")
        return "button"

    def close(self) -> None:
        pass
