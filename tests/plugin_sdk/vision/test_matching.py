from dataclasses import replace

import cv2
import numpy as np
import pytest

from bca.plugin_sdk.vision import (
    MatchOptions,
    MatchStatus,
    PixelRect,
    PreprocessMode,
    VisionMatchError,
    decode_frame,
    match_frame,
    match_templates,
)
from bca.plugin_sdk.vision.matching import score_map

from .conftest import frame_of


@pytest.mark.parametrize("mode", [PreprocessMode.RGB, PreprocessMode.GRAY])
@pytest.mark.parametrize("masked", [False, True])
def test_independent_exhaustive_oracle(mode, masked, make_template):
    rng = np.random.default_rng(4202)
    image = rng.integers(0, 256, (7, 9, 3), dtype=np.uint8)
    template = rng.integers(0, 256, (2, 3, 3), dtype=np.uint8)
    mask = np.array([[0, 64, 128], [255, 128, 64]], dtype=np.uint8) if masked else None
    loaded = make_template(template, mask)
    if mode is PreprocessMode.GRAY:
        image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        template = cv2.cvtColor(template, cv2.COLOR_RGB2GRAY)
    weights = np.ones((2, 3)) if mask is None else mask.astype(np.float64) / 255
    scores, _, _ = score_map(image, template, None if mask is None else weights.astype(np.float32))
    oracle = np.empty((6, 7))
    for y in range(6):
        for x in range(7):
            error = 0.0
            for v in range(2):
                for u in range(3):
                    actual = np.atleast_1d(image[y + v, x + u])
                    target = np.atleast_1d(template[v, u])
                    error += (
                        sum((float(a) - float(b)) ** 2 for a, b in zip(actual, target, strict=True))
                        * weights[v, u] ** 2
                    )
            channels = 3 if mode is PreprocessMode.RGB else 1
            oracle[y, x] = 1 - np.sqrt(error / (channels * 255**2 * (weights**2).sum()))
    np.testing.assert_allclose(scores, oracle, atol=2e-6, rtol=0)
    # The public best candidate is also compared against the independent global maximum.
    rgb = image if mode is PreprocessMode.RGB else np.repeat(image[:, :, None], 3, axis=2)
    result = match_frame(frame_of(rgb), [loaded], options=MatchOptions(mode=mode, threshold=1))
    y, x = np.unravel_index(oracle.argmax(), oracle.shape)
    assert (result.best_candidate.bbox.x, result.best_candidate.bbox.y) == (x, y)
    assert result.best_candidate.score == pytest.approx(oracle[y, x], abs=2e-8)


@pytest.mark.parametrize("value", [0, 80, 255])
def test_constant_and_threshold_endpoints(value, make_template):
    pixels = np.full((4, 5, 3), value, np.uint8)
    loaded = make_template(pixels)
    result = match_frame(frame_of(pixels), [loaded], options=MatchOptions(threshold=1))
    assert result.status is MatchStatus.MATCHED and result.matches[0].score == 1
    opposite = np.full_like(pixels, 255 if value == 0 else 0)
    result = match_frame(frame_of(opposite), [loaded], options=MatchOptions(threshold=0))
    assert result.status is MatchStatus.MATCHED
    assert result.matches[0].score == pytest.approx(1 - abs(value - int(opposite[0, 0, 0])) / 255)


def test_competition_repeat_order_and_limits(make_template):
    rng = np.random.default_rng(11)
    pixels = rng.integers(0, 256, (7, 9, 3), dtype=np.uint8)
    template = make_template(pixels)
    screen = np.full((60, 90, 3), 128, np.uint8)
    for x, y in [(5, 8), (55, 35)]:
        screen[y : y + 7, x : x + 9] = pixels
    frame = frame_of(screen)
    decoded = decode_frame(frame)
    result = match_templates(decoded, [template])
    assert [(c.bbox.x, c.bbox.y) for c in result.matches] == [(5, 8), (55, 35)]
    rival = replace(
        template, variant_id="rival", selection=replace(template.selection, variant_id="rival")
    )
    for order in ([template, rival], [rival, template]):
        ambiguous = match_templates(decoded, order)
        assert ambiguous.status is MatchStatus.AMBIGUOUS and not ambiguous.matches
        assert len(ambiguous.ambiguous) == 2
        assert [c.variant_id for c in ambiguous.ambiguous[0]] == ["base", "rival"]
    limited = match_templates(decoded, [template], options=MatchOptions(max_results=1))
    assert len(limited.matches) == 1 and "result_limit_reached" in limited.diagnostics
    weaker_pixels = np.maximum(pixels.astype(int) - 10, 0).astype(np.uint8)
    weaker = make_template(weaker_pixels)
    weaker = replace(
        weaker, asset_id="ui.other", selection=replace(weaker.selection, asset_id="ui.other")
    )
    winner = match_templates(
        decoded, [template, weaker], options=MatchOptions(threshold=0.9, ambiguity_margin=0.01)
    )
    assert winner.status is MatchStatus.MATCHED
    assert all(c.asset_id == "ui.target" for c in winner.matches)


def test_roi_best_missing_and_oversized(make_template):
    pixels = np.arange(72, dtype=np.uint8).reshape(4, 6, 3)
    template = make_template(pixels)
    screen = np.full((20, 30, 3), 200, np.uint8)
    screen[8:12, 15:21] = pixels
    frame = frame_of(screen)
    result = match_frame(
        frame, [template], options=MatchOptions(roi=PixelRect(x=12, y=6, width=12, height=10))
    )
    assert result.matches[0].bbox == PixelRect(x=15, y=8, width=6, height=4)
    assert result.matches[0].center == (17.5, 9.5)
    assert result.frame_id == frame.frame_id and result.page_id == frame.page_id
    small = match_frame(
        frame, [template], options=MatchOptions(roi=PixelRect(x=0, y=0, width=2, height=2))
    )
    assert small.reason == "template_larger_than_roi" and small.best_candidate is None
    missing = match_frame(
        frame, [template], options=MatchOptions(roi=PixelRect(x=0, y=0, width=10, height=5))
    )
    assert missing.reason == "below_threshold" and missing.best_candidate is not None
    assert missing.timing.decode_ms > 0
    assert match_templates(decode_frame(frame), [template]).timing.decode_ms == 0


def test_native_failures_and_negative_diagnostics(monkeypatch, make_template):
    template = make_template(np.zeros((2, 2, 3), np.uint8))
    frame = frame_of(np.zeros((4, 4, 3), np.uint8))
    monkeypatch.setattr(cv2, "matchTemplate", lambda *a, **k: np.full((3, 3), -1, np.float32))
    assert "negative_ssd_clamped" in match_frame(frame, [template]).diagnostics
    monkeypatch.setattr(cv2, "matchTemplate", lambda *a, **k: np.full((3, 3), np.nan, np.float32))
    with pytest.raises(VisionMatchError, match="nonfinite"):
        match_frame(frame, [template])

    def fail(*a, **k):
        raise cv2.error("sensitive backend detail")

    monkeypatch.setattr(cv2, "matchTemplate", fail)
    with pytest.raises(VisionMatchError, match="OpenCV") as caught:
        match_frame(frame, [template])
    assert "sensitive" not in str(caught.value)


def test_plateau_bounds_and_ambiguity_survives_output_cap(make_template):
    template = make_template(np.zeros((2, 2, 3), np.uint8))
    frame = frame_of(np.zeros((40, 40, 3), np.uint8))
    options = MatchOptions(threshold=1, max_proposals_per_variant=3, max_results=1)
    result = match_frame(frame, [template], options=options)
    assert len(result.matches) == 1
    assert result.matches[0].bbox == PixelRect(x=0, y=0, width=2, height=2)
    assert "proposal_limit_reached" in result.diagnostics
    rival = replace(
        template, asset_id="ui.rival", selection=replace(template.selection, asset_id="ui.rival")
    )
    result = match_frame(frame, [template, rival], options=options)
    assert result.status is MatchStatus.AMBIGUOUS and not result.matches
    assert len(result.ambiguous) == 1 and len(result.ambiguous[0]) == 2
    assert "result_limit_reached" in result.diagnostics


def test_float_boundary_and_scale_deduplication(make_template):
    template = make_template(np.zeros((2, 2, 3), np.uint8))
    frame = frame_of(np.full((2, 2, 3), 51, np.uint8))
    for threshold, expected in [
        (0.8, MatchStatus.MATCHED),
        (0.8 + 5e-10, MatchStatus.MATCHED),
        (0.8 + 2e-9, MatchStatus.NOT_FOUND),
    ]:
        result = match_frame(
            frame,
            [template],
            options=MatchOptions(threshold=threshold, scales=((1.01, 1.01), (1, 1), (1, 1))),
        )
        assert result.status is expected
        assert result.best_candidate.scale_x == 1
        assert result.best_candidate.score == pytest.approx(0.8)
