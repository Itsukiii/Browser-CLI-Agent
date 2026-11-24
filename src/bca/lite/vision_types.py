"""Immutable single-image recognition contracts; no plugin or polling lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from .bridge import ObservationRef

Box = tuple[int, int, int, int]


class VisionError(RuntimeError):
    """Resource, lifecycle or capture failure with no valid recognition batch."""


class RecognitionStatus(StrEnum):
    MATCHED = "MATCHED"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    ERROR = "ERROR"


@dataclass(frozen=True)
class TemplateRequest:
    key: str
    template: str
    roi: Box | None = None
    threshold: float = 0.9
    unique: bool = True


@dataclass(frozen=True)
class OCRRequest:
    key: str
    roi: Box | None = None
    threshold: float = 0.3
    expected: tuple[str, ...] = ()
    unique: bool = True
    only_rec: bool = False


RecognitionRequest = TemplateRequest | OCRRequest


@dataclass(frozen=True)
class Candidate:
    box: Box
    score: float
    text: str | None = None


@dataclass(frozen=True)
class RecognitionResult:
    request_key: str
    algorithm: str
    status: RecognitionStatus
    candidates: tuple[Candidate, ...] = ()
    all_candidates: tuple[Candidate, ...] = ()
    best: Candidate | None = None  # Diagnostic only, never an authorization.
    job_id: int | None = None
    job_status: str | None = None
    reco_id: int | None = None
    hit: bool | None = None
    raw_detail_json: str | None = None
    diagnostic: str | None = None


@dataclass(frozen=True, eq=False)
class CaptureContext:
    source_ref: ObservationRef
    binding: tuple[str | None, str | None, int]
    width: int
    height: int
    pixels: bytes = field(repr=False)
    coordinate_space: Literal["maa_image_pixels"] = "maa_image_pixels"

    @property
    def image(self) -> NDArray[np.uint8]:
        """Bytes-backed view cannot be made writable with setflags."""
        return np.frombuffer(self.pixels, dtype=np.uint8).reshape(self.height, self.width, 3)


@dataclass(frozen=True)
class RecognitionBatch:
    capture: CaptureContext
    results: tuple[RecognitionResult, ...]
    completed_at: float
    source_current: bool
    expired: bool
    # These flags describe completion time only. Actions must revalidate/authorize.


@dataclass(frozen=True)
class CloseReport:
    released: bool
    worker_thread: int | None
    destroyed: tuple[str, ...]
    errors: tuple[str, ...]
    stop_status: str | None = None
