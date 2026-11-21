"""Safe, SDK-local failures; ordinary misses are results, not exceptions."""

from bca.core.errors import BCAError


class VisionError(BCAError):
    code = "vision.error"


class VisionInputError(VisionError):
    code = "vision.input"


class VisionDecodeError(VisionError):
    code = "vision.decode"


class VisionMatchError(VisionError):
    code = "vision.match"
