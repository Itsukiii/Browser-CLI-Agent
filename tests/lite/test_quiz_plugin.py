"""Pure semantics tests; no claim of native image recognition."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from bca.lite.plugin import ReadIntent
from bca.lite.quiz import QuizPlugin, decode_quiz_state, quiz_roi
from bca.lite.vision_resources import ResourceSpec
from bca.lite.vision_types import Candidate, RecognitionResult
from bca.lite.vision_types import RecognitionStatus as S


def batch(**changes):
    fields = dict(
        round="000001",
        time="9.0",
        question="3",
        score="-305",
        digit_A="1",
        digit_B="3",
        digit_C="7",
        digit_D="9",
    )
    fields.update(changes)
    rows = [
        RecognitionResult(k, "OCR", S.MATCHED, (Candidate((1, 2, 3, 4), 0.99, v),))
        for k, v in fields.items()
    ]
    rows += [
        RecognitionResult(
            f"{letter}_{style}",
            "TemplateMatch",
            S.MATCHED if style == "neutral" else S.NOT_FOUND,
            (Candidate((1, 2, 3, 4), 0.99),) if style == "neutral" else (),
        )
        for letter in "ABCD"
        for style in ("neutral", "selected")
    ]
    rows.append(
        RecognitionResult("confirm", "TemplateMatch", S.MATCHED, (Candidate((1, 2, 3, 4), 0.99),))
    )
    return SimpleNamespace(results=tuple(rows))


@pytest.fixture
def plugin(tmp_path):
    return QuizPlugin(ResourceSpec(tmp_path))


@pytest.mark.parametrize("score", ["0", "-1", "-20", "-305", "12", "345", "6789"])
def test_scores_and_signature(plugin, score):
    first = plugin.observe(batch(score=score))
    second = plugin.observe(batch(score=score, time="8.0"))
    assert decode_quiz_state(first).score == int(score)
    assert first.signature == second.signature
    assert len(first.targets) == 5
    assert first.interaction_revision == "000001"
    assert plugin.observe(batch(round="000002", score=score)).signature != first.signature


@pytest.mark.parametrize(
    "changes",
    [
        dict(round="000000"),
        dict(round="abc"),
        dict(question="33"),
        dict(digit_A="3"),
        dict(question="2"),
        dict(score="-3O5"),
        dict(time="11.0"),
        dict(score="1.0"),
    ],
)
def test_inconsistent_fields_never_publish_targets(plugin, changes):
    state = plugin.observe(batch(**changes))
    assert state.status == S.AMBIGUOUS
    assert not state.targets
    with pytest.raises(ValueError):
        decode_quiz_state(state)


@pytest.mark.parametrize("status", [S.NOT_FOUND, S.AMBIGUOUS, S.ERROR])
def test_no_old_score_or_best_fallback(plugin, status):
    assert plugin.observe(batch()).status == S.MATCHED
    current = batch()
    current.results = tuple(
        replace(r, status=status, candidates=(), best=Candidate((1, 2, 3, 4), 0.99, "-305"))
        if r.request_key == "score"
        else r
        for r in current.results
    )
    state = plugin.observe(current)
    assert state.status == status
    assert not state.targets and state.payload is None
    assert "当前分数无法识别" in plugin.format_state(state)


def test_multiple_selected_and_generic_writes_rejected(plugin):
    current = batch()
    current.results = tuple(
        replace(r, status=S.MATCHED) if r.request_key.endswith("selected") else r
        for r in current.results
    )
    assert plugin.observe(current).status == S.AMBIGUOUS
    assert isinstance(plugin.parse_command("?"), ReadIntent)
    with pytest.raises(ValueError):
        plugin.parse_command("A")
    with pytest.raises(ValueError):
        plugin.resolve(None, plugin.observe(batch()))


def test_plan_geometry_and_confidence(plugin):
    assert quiz_roi((1920, 1280), (80, 45, 400, 65)) == (160, 90, 800, 130)
    assert len(plugin.plan((960, 640))) == 17
    assert all(r.threshold == 0.9 for r in plugin.plan((960, 640)))
    with pytest.raises(ValueError):
        plugin.plan((10, 10))
