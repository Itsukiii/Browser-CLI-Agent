"""Pure fixture business logic: template button plus optional visible OCR round number."""

from __future__ import annotations

import base64
import time
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import as_file, files
from pathlib import Path

from bca.lite.plugin import ActionIntent, BusinessState, Intent, ReadIntent, VisualTarget
from bca.lite.vision_resources import ResourceSpec
from bca.lite.vision_types import (
    OCRRequest,
    RecognitionBatch,
    RecognitionRequest,
    RecognitionStatus,
    TemplateRequest,
)


@contextmanager
def fixture_bundle() -> Iterator[Path]:
    """Keep this context open until Maa Resource has been completely released."""
    with as_file(files("bca.lite").joinpath("resources/fixture")) as path:
        yield path.resolve()


def fixture_html(bundle: Path) -> str:
    image = base64.b64encode((bundle / "image/marker.png").read_bytes()).decode("ascii")
    return (
        (bundle / "page.html")
        .read_text(encoding="utf-8")
        .replace("MARKER_DATA", "data:image/png;base64," + image)
    )


class FixturePlugin:
    plugin_id = "lite-fixture"

    def __init__(self, resources: ResourceSpec, *, roi: bool = False) -> None:
        self.resources = resources
        self.roi = roi

    def plan(self, image_size: tuple[int, int]) -> tuple[RecognitionRequest, ...]:
        width, height = image_size
        button_roi = (0, 0, width, height // 2) if self.roi else None
        number_roi = (0, height // 2, width, height - height // 2) if self.roi else None
        requests: tuple[RecognitionRequest, ...] = (
            TemplateRequest("button", "marker.png", roi=button_roi),
        )
        if self.resources.ocr is not None:
            requests += (OCRRequest("round", roi=number_roi),)
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
