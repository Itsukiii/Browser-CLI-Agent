"""Bounded proposals, weighted RMSE scores, deterministic spatial competition."""

from collections.abc import Sequence
from dataclasses import replace
from time import perf_counter
from typing import cast

import cv2
import numpy as np
from numpy.typing import NDArray

from bca.core.protocol import Frame
from bca.plugin_sdk.assets import LoadedTemplate

from .decode import decode_frame
from .errors import VisionInputError, VisionMatchError
from .models import (
    EPSILON,
    DecodedFrame,
    MatchCandidate,
    MatchOptions,
    MatchResult,
    MatchStatus,
    PixelRect,
    VisionTiming,
)
from .preprocess import prepare_frame, prepare_template, scaled_size, validate_template

DEFAULT_OPTIONS = MatchOptions()


def sort_key(c: MatchCandidate) -> tuple[float, str, str, int, int, float, float]:
    return (-c.score, c.asset_id, c.variant_id, c.bbox.y, c.bbox.x, c.scale_x, c.scale_y)


def overlap(a: PixelRect, b: PixelRect) -> float:
    area = max(0, min(a.x + a.width, b.x + b.width) - max(a.x, b.x)) * max(
        0, min(a.y + a.height, b.y + b.height) - max(a.y, b.y)
    )
    return area / (a.width * a.height + b.width * b.height - area)


def score_map(
    image: NDArray[np.uint8], template: NDArray[np.uint8], weights: NDArray[np.float32] | None
) -> tuple[NDArray[np.float32], float, bool]:
    channels = 1 if template.ndim == 2 else 3
    mass = (
        template.shape[0] * template.shape[1]
        if weights is None
        else float(np.square(weights.astype(np.float64)).sum())
    )
    denominator = channels * 65025 * mass
    ssd = cast(NDArray[np.float32], cv2.matchTemplate(image, template, cv2.TM_SQDIFF, mask=weights))
    if not np.all(np.isfinite(ssd)):
        raise VisionMatchError("nonfinite SSD output")
    negative = bool(np.any(ssd < 0))
    np.maximum(ssd, 0, out=ssd)
    ssd /= denominator
    np.sqrt(ssd, out=ssd)
    np.subtract(1, ssd, out=ssd)
    np.clip(ssd, 0, 1, out=ssd)
    return ssd, denominator, negative


def exact_score(
    image: NDArray[np.uint8],
    template: NDArray[np.uint8],
    weights: NDArray[np.float32] | None,
    denominator: float,
    x: int,
    y: int,
) -> float:
    h, w = template.shape[:2]
    delta = template.astype(np.float64) - image[y : y + h, x : x + w]
    if weights is not None:
        delta *= weights if delta.ndim == 2 else weights[:, :, None]
    return float(np.clip(1 - np.sqrt(np.square(delta).sum() / denominator), 0, 1))


def proposals(
    scores: NDArray[np.float32], width: int, height: int, limit: int, iou: float
) -> list[tuple[int, int]]:
    # 3x3 maxima retain plateaus; bounded greedy suppression never enumerates them.
    peaks = scores.copy()
    peaks[scores < cv2.dilate(scores, np.ones((3, 3), np.uint8))] = -1
    result: list[tuple[int, int]] = []
    for _ in range(limit):
        _, maximum, _, point = cv2.minMaxLoc(peaks)
        if maximum < 0:
            break
        x, y = point
        result.append((x, y))
        x0, x1 = max(0, x - width + 1), min(peaks.shape[1], x + width)
        y0, y1 = max(0, y - height + 1), min(peaks.shape[0], y + height)
        dx = np.abs(np.arange(x0, x1) - x)[None, :]
        dy = np.abs(np.arange(y0, y1) - y)[:, None]
        intersection = (width - dx) * (height - dy)
        suppress = intersection / (2 * width * height - intersection) > iou + EPSILON
        peaks[y0:y1, x0:x1][suppress] = -1
        peaks[y, x] = -1  # Also terminates plateaus when nms_iou=1.
    return result


def match_templates(
    decoded: DecodedFrame,
    templates: Sequence[LoadedTemplate],
    *,
    options: MatchOptions = DEFAULT_OPTIONS,
) -> MatchResult:
    start = perf_counter()
    if not isinstance(options, MatchOptions):
        raise VisionInputError("expected MatchOptions")
    if not isinstance(templates, Sequence) or not 1 <= len(templates) <= 256:
        raise VisionInputError("expected 1..256 templates")
    identities: set[tuple[str, str]] = set()
    for template in templates:
        validate_template(template)
        key = (template.asset_id, template.variant_id)
        if key in identities:
            raise VisionInputError("duplicate asset/variant input")
        identities.add(key)
    try:
        return _match(decoded, templates, options, start)
    except cv2.error as exc:
        raise VisionMatchError("OpenCV matching or preprocessing failed") from exc


def _match(
    decoded: DecodedFrame, templates: Sequence[LoadedTemplate], options: MatchOptions, start: float
) -> MatchResult:
    image, roi = prepare_frame(decoded, options)
    preprocess = perf_counter() - start
    matching = 0.0
    postprocess = 0.0
    candidates: list[MatchCandidate] = []
    diagnostics: set[str] = set()
    for template in sorted(templates, key=lambda t: (t.asset_id, t.variant_id)):
        variant: list[MatchCandidate] = []
        sizes: set[tuple[int, int]] = set()
        for sx, sy in sorted(set(options.scales)):
            size = scaled_size(template, (sx, sy))
            if size in sizes:
                continue
            sizes.add(size)
            w, h = size
            if w > roi.width or h > roi.height:
                diagnostics.add("scale_larger_than_roi")
                continue
            tick = perf_counter()
            pixels, weights = prepare_template(template, size, options.mode)
            preprocess += perf_counter() - tick
            tick = perf_counter()
            scores, denominator, negative = score_map(image, pixels, weights)
            matching += perf_counter() - tick
            tick = perf_counter()
            if negative:
                diagnostics.add("negative_ssd_clamped")
            points = proposals(scores, w, h, options.max_proposals_per_variant, options.nms_iou)
            if len(points) == options.max_proposals_per_variant:
                diagnostics.add("proposal_limit_reached")
            for x, y in points:
                # Float64 patch refinement removes cv2 float32 cancellation at exact matches.
                score = exact_score(image, pixels, weights, denominator, x, y)
                bbox = PixelRect(x=x + roi.x, y=y + roi.y, width=w, height=h)
                variant.append(
                    MatchCandidate(
                        asset_id=template.asset_id,
                        variant_id=template.variant_id,
                        frame_id=decoded.frame.frame_id,
                        bbox=bbox,
                        center=(bbox.x + (w - 1) / 2, bbox.y + (h - 1) / 2),
                        score=score,
                        threshold=options.threshold,
                        scale_x=sx,
                        scale_y=sy,
                        selection=template.selection,
                    )
                )
            del scores
            postprocess += perf_counter() - tick
        tick = perf_counter()
        kept: list[MatchCandidate] = []
        for candidate in sorted(variant, key=sort_key):
            if not any(
                overlap(candidate.bbox, prior.bbox) > options.nms_iou + EPSILON for prior in kept
            ):
                kept.append(candidate)
                if len(kept) == options.max_proposals_per_variant:
                    break
        candidates.extend(kept)
        postprocess += perf_counter() - tick
    tick = perf_counter()
    candidates.sort(key=sort_key)
    best = candidates[0] if candidates else None
    pending = [c for c in candidates if c.score + EPSILON >= options.threshold]
    matches: list[MatchCandidate] = []
    ambiguous: list[tuple[MatchCandidate, ...]] = []
    # Greedy anchor groups: overlap is compared with the current highest score, not transitive.
    while pending:
        anchor = pending.pop(0)
        group = [anchor]
        remaining: list[MatchCandidate] = []
        for c in pending:
            if overlap(anchor.bbox, c.bbox) > options.nms_iou + EPSILON:
                if (anchor.asset_id, anchor.variant_id) != (c.asset_id, c.variant_id):
                    group.append(c)
            else:
                remaining.append(c)
        pending = remaining
        competitors = tuple(
            c for c in group if anchor.score - c.score <= options.ambiguity_margin + EPSILON
        )
        if len(competitors) > 1:
            ambiguous.append(competitors)
        else:
            matches.append(anchor)
    # Determine status before output truncation, so hidden ambiguity cannot authorize input.
    status = (
        MatchStatus.AMBIGUOUS
        if ambiguous
        else MatchStatus.MATCHED
        if matches
        else MatchStatus.NOT_FOUND
    )
    reason = (
        "ambiguous_candidates"
        if ambiguous
        else "matched"
        if matches
        else "below_threshold"
        if best
        else "template_larger_than_roi"
    )
    if len(matches) > options.max_results or sum(map(len, ambiguous)) > options.max_results:
        diagnostics.add("result_limit_reached")
    # Keep full competition groups, but cap total candidates. One group may be truncated.
    budget = max(2, options.max_results)
    bounded: list[tuple[MatchCandidate, ...]] = []
    for group_tuple in ambiguous:
        if budget < 2:
            break
        bounded.append(group_tuple[: max(2, budget)])
        budget -= len(bounded[-1])
    postprocess += perf_counter() - tick
    return MatchResult(
        frame_id=decoded.frame.frame_id,
        page_id=decoded.frame.page_id,
        status=status,
        matches=tuple(matches[: options.max_results]),
        ambiguous=tuple(bounded),
        best_candidate=best,
        reason=reason,
        options=options,
        diagnostics=tuple(sorted(diagnostics)),
        timing=VisionTiming(
            preprocess_ms=preprocess * 1000,
            match_ms=matching * 1000,
            postprocess_ms=postprocess * 1000,
            total_ms=(perf_counter() - start) * 1000,
        ),
    )


def match_frame(
    frame: Frame, templates: Sequence[LoadedTemplate], *, options: MatchOptions = DEFAULT_OPTIONS
) -> MatchResult:
    start = perf_counter()
    decoded = decode_frame(frame)
    decode_ms = (perf_counter() - start) * 1000
    result = match_templates(decoded, templates, options=options)
    return replace(
        result,
        timing=replace(
            result.timing, decode_ms=decode_ms, total_ms=(perf_counter() - start) * 1000
        ),
    )
