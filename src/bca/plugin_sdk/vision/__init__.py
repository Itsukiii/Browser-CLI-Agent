"""Optional RGB template matching. Install browser-cli-agent[vision]."""

from .decode import decode_frame
from .errors import VisionDecodeError, VisionError, VisionInputError, VisionMatchError
from .matching import match_frame, match_templates
from .models import (
    DecodedFrame,
    MatchCandidate,
    MatchOptions,
    MatchResult,
    MatchStatus,
    PixelRect,
    PreprocessMode,
    VisionTiming,
)

__all__ = [
    "decode_frame",
    "match_frame",
    "match_templates",
    "DecodedFrame",
    "MatchCandidate",
    "MatchOptions",
    "MatchResult",
    "MatchStatus",
    "PixelRect",
    "PreprocessMode",
    "VisionTiming",
    "VisionError",
    "VisionDecodeError",
    "VisionInputError",
    "VisionMatchError",
]
