"""Immutable SDK snapshots; coordinates always refer to the original Frame."""

import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

from bca.core.protocol import Frame
from bca.plugin_sdk.assets import AssetSelection

from .errors import VisionInputError

MAX_PIXELS = 16_777_216
EPSILON = 1e-9


def number(value: object, low: float, high: float) -> None:
    if type(value) not in (int, float):
        raise VisionInputError("expected a built-in int or float")
    assert isinstance(value, (int, float))
    if not low <= value <= high or not math.isfinite(value):
        raise VisionInputError("number outside supported range")


@dataclass(frozen=True, kw_only=True, slots=True, eq=False)
class DecodedFrame:
    frame: Frame
    image: NDArray[np.uint8]


@dataclass(frozen=True, kw_only=True, slots=True)
class PixelRect:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        for name in ("x", "y", "width", "height"):
            value = getattr(self, name)
            if type(value) is not int or value < (1 if name in ("width", "height") else 0):
                raise VisionInputError("invalid pixel rectangle")


class PreprocessMode(StrEnum):
    RGB = "rgb"
    GRAY = "gray"


@dataclass(frozen=True, kw_only=True, slots=True)
class MatchOptions:
    threshold: float = 0.96
    roi: PixelRect | None = None
    mode: PreprocessMode = PreprocessMode.RGB
    scales: tuple[tuple[float, float], ...] = ((1.0, 1.0),)
    nms_iou: float = 0.45
    ambiguity_margin: float = 0.02
    max_results: int = 32
    max_proposals_per_variant: int = 128

    def __post_init__(self) -> None:
        for value in (self.threshold, self.nms_iou, self.ambiguity_margin):
            number(value, 0, 1)
        if self.roi is not None and not isinstance(self.roi, PixelRect):
            raise VisionInputError("roi must be PixelRect")
        if not isinstance(self.mode, PreprocessMode):
            raise VisionInputError("mode must be PreprocessMode")
        if type(self.scales) is not tuple or not 1 <= len(self.scales) <= 16:
            raise VisionInputError("expected 1..16 immutable scales")
        for pair in self.scales:
            if type(pair) is not tuple or len(pair) != 2:
                raise VisionInputError("scale must be an immutable pair")
            for value in pair:
                number(value, 0.25, 4)
        for value in (self.max_results, self.max_proposals_per_variant):
            if type(value) is not int or not 1 <= value <= 4096:
                raise VisionInputError("candidate limits must be integers in 1..4096")


class MatchStatus(StrEnum):
    MATCHED = "matched"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, kw_only=True, slots=True)
class MatchCandidate:
    asset_id: str
    variant_id: str
    frame_id: str
    bbox: PixelRect
    center: tuple[float, float]
    score: float
    threshold: float
    scale_x: float
    scale_y: float
    selection: AssetSelection


@dataclass(frozen=True, kw_only=True, slots=True)
class VisionTiming:
    decode_ms: float = 0
    preprocess_ms: float = 0
    match_ms: float = 0
    postprocess_ms: float = 0
    total_ms: float = 0


@dataclass(frozen=True, kw_only=True, slots=True)
class MatchResult:
    frame_id: str
    page_id: str
    status: MatchStatus
    matches: tuple[MatchCandidate, ...]
    ambiguous: tuple[tuple[MatchCandidate, ...], ...]
    best_candidate: MatchCandidate | None
    reason: str
    timing: VisionTiming
    options: MatchOptions
    diagnostics: tuple[str, ...] = ()
