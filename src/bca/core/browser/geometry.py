"""Read-only content viewport geometry shared by capture and input."""

import logging
import math
from dataclasses import dataclass

from bca.core.protocol import JsonObject

from .errors import BrowserError
from .session import BrowserSession

logger = logging.getLogger(__name__)


class GeometryError(BrowserError):
    code = "browser.geometry"


@dataclass(frozen=True)
class Geometry:
    width: float
    height: float
    scroll_x: float
    scroll_y: float
    dpr: float
    zoom: float
    document: tuple[str, float]
    visual_size: tuple[float, float]
    layout_size: tuple[float, float]
    layout_scroll: tuple[float, float]
    surface_size: tuple[float, float]


_MEASURE = """(() => ({dpr:devicePixelRatio, x:scrollX, y:scrollY,
    surfaceWidth:innerWidth, surfaceHeight:innerHeight,
    href:location.href, timeOrigin:performance.timeOrigin}))()"""


def _numeric(obj: JsonObject, key: str, *, positive_only: bool = False) -> float:
    value = obj.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or (positive_only and value <= 0)
    ):
        raise GeometryError(f"invalid viewport measurement: {key}")
    return float(value)


def _same(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=0, abs_tol=1e-6)


async def measure_geometry(session: BrowserSession) -> Geometry:
    metrics = await session.send("Page.getLayoutMetrics")
    visual, layout = metrics.get("cssVisualViewport"), metrics.get("cssLayoutViewport")
    if not isinstance(visual, dict) or not isinstance(layout, dict):
        raise GeometryError("CDP CSS viewport metrics are missing")
    visual_width = _numeric(visual, "clientWidth", positive_only=True)
    visual_height = _numeric(visual, "clientHeight", positive_only=True)
    layout_width = _numeric(layout, "clientWidth", positive_only=True)
    layout_height = _numeric(layout, "clientHeight", positive_only=True)
    layout_x, layout_y = _numeric(layout, "pageX"), _numeric(layout, "pageY")
    if (
        not _same(_numeric(visual, "scale", positive_only=True), 1)
        or not _same(_numeric(visual, "offsetX"), 0)
        or not _same(_numeric(visual, "offsetY"), 0)
    ):
        raise GeometryError("pinch-zoom/offset visual viewport is unsupported in this stage")
    # The layout content rectangle and the visible rectangle need not have
    # equal sizes (scrollbars/emulation/rounding). At their shared origin,
    # only their intersection is both visible and part of the content area.
    width, height = min(visual_width, layout_width), min(visual_height, layout_height)
    result = await session.send("Runtime.evaluate", {"expression": _MEASURE, "returnByValue": True})
    remote = result.get("result")
    values = remote.get("value") if isinstance(remote, dict) else None
    if "exceptionDetails" in result or not isinstance(values, dict):
        raise GeometryError("viewport runtime measurement failed")
    x, y = _numeric(visual, "pageX"), _numeric(visual, "pageY")
    # CDP LayoutViewport pageX/Y are integral; visual/runtime scroll can be
    # fractional at desktop zoom. Permit at most one CSS pixel of rounding,
    # but never use the rounded layout offset to position the screenshot.
    if abs(layout_x - x) > 1 or abs(layout_y - y) > 1:
        raise GeometryError(
            f"layout/visual scroll origins disagree: layout=({layout_x},{layout_y}), "
            f"visual=({x},{y})"
        )
    # Edge desktop zoom can expose float32 rounding in window.scrollY while
    # CDP pageY is exact (80%: 119.99999237060547 versus 120). This tolerance
    # applies only to duplicate scroll measurements, not scale or offsets.
    if not math.isclose(x, _numeric(values, "x"), rel_tol=0, abs_tol=1e-4) or not math.isclose(
        y, _numeric(values, "y"), rel_tol=0, abs_tol=1e-4
    ):
        raise GeometryError("scroll position changed during viewport measurement")
    href = values.get("href")
    if not isinstance(href, str):
        raise GeometryError("document URL measurement is missing")
    sw = _numeric(values, "surfaceWidth", positive_only=True)
    sh = _numeric(values, "surfaceHeight", positive_only=True)
    if width > sw or height > sh:
        raise GeometryError("content viewport exceeds native surface")
    geometry = Geometry(
        width,
        height,
        x,
        y,
        _numeric(values, "dpr", positive_only=True),
        _numeric(visual, "zoom", positive_only=True),
        (href, _numeric(values, "timeOrigin", positive_only=True)),
        (visual_width, visual_height),
        (layout_width, layout_height),
        (layout_x, layout_y),
        (sw, sh),
    )
    logger.debug(
        "Capture geometry visual=%s layout=%s layout_scroll=%s dpr=%s zoom=%s surface=%s",
        geometry.visual_size,
        geometry.layout_size,
        geometry.layout_scroll,
        geometry.dpr,
        geometry.zoom,
        geometry.surface_size,
    )
    return geometry
