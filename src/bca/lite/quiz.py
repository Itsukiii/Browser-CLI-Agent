"""Pure Quiz visual semantics. No browser, DOM or native handles."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .plugin import ActionIntent, BusinessState, Intent, ReadIntent, VisualTarget
from .vision_resources import ResourceSpec
from .vision_types import (
    Box,
    OCRRequest,
    RecognitionBatch,
    RecognitionRequest,
    RecognitionStatus,
    TemplateRequest,
)


@dataclass(frozen=True)
class QuizSnapshot:
    round_mark: str
    question: int
    options: tuple[int, int, int, int]
    score: int
    selected: str | None
    time_left: float


def decode_quiz_state(state: BusinessState) -> QuizSnapshot:
    value = state.payload
    if state.status != RecognitionStatus.MATCHED or not isinstance(value, tuple) or len(value) != 6:
        raise ValueError("complete trusted Quiz snapshot required")
    mark, question, options, score, selected, time_left = value
    if not (
        isinstance(mark, str)
        and type(question) is int
        and type(score) is int
        and isinstance(options, tuple)
        and len(options) == 4
        and all(type(n) is int for n in options)
        and (selected is None or isinstance(selected, str))
        and isinstance(time_left, float)
    ):
        raise ValueError("invalid Quiz payload")
    return QuizSnapshot(mark, question, options, score, selected, time_left)  # type: ignore[arg-type]


def quiz_roi(image_size: tuple[int, int], box: Box) -> Box:
    width, height = image_size
    scale = min(width / 960, height / 640)
    ox, oy = (width - 960 * scale) / 2, (height - 640 * scale) / 2
    x, y, w, h = box
    left, top = math.floor(ox + x * scale), math.floor(oy + y * scale)
    right, bottom = math.ceil(ox + (x + w) * scale), math.ceil(oy + (y + h) * scale)
    return left, top, right - left, bottom - top


class QuizPlugin:
    plugin_id = "quiz"

    def __init__(self, resources: ResourceSpec) -> None:
        self.resources = resources

    def plan(self, image_size: tuple[int, int]) -> tuple[RecognitionRequest, ...]:
        size = round(32 * min(image_size[0] / 960, image_size[1] / 640))
        if not 8 <= size <= 128:
            raise ValueError("Quiz image scale outside prepared template range")
        fields = {
            "round": (80, 45, 400, 65),
            "time": (720, 45, 180, 65),
            "score": (80, 515, 380, 70),
        }
        requests: list[RecognitionRequest] = [
            OCRRequest(key, quiz_roi(image_size, box), threshold=0.7) for key, box in fields.items()
        ]
        digits = {"question": (455, 141, 50, 68)}
        digits.update(
            {f"digit_{letter}": (125 + i * 220, 328, 50, 72) for i, letter in enumerate("ABCD")}
        )
        height = round(60 * min(image_size[0] / 960, image_size[1] / 640))
        for key, box in digits.items():
            roi = quiz_roi(image_size, box)
            requests.append(OCRRequest(key, roi, threshold=0, only_rec=True))
            requests.extend(
                TemplateRequest(
                    f"{key}_tpl_{digit}", f"digit-{digit}-{height}.png", roi, threshold=0.9
                )
                for digit in range(10)
            )
        for i, letter in enumerate("ABCD"):
            for style in ("neutral", "selected"):
                requests.append(
                    TemplateRequest(
                        f"{letter}_{style}",
                        f"{style}-{size}.png",
                        quiz_roi(image_size, (60 + i * 220, 300, 180, 130)),
                    )
                )
        requests.append(
            TemplateRequest(
                "confirm", f"neutral-{size}.png", quiz_roi(image_size, (610, 510, 260, 90))
            )
        )
        return tuple(requests)

    def observe(self, batch: RecognitionBatch) -> BusinessState:
        results = {r.request_key: r for r in batch.results}

        def failed(status: RecognitionStatus, reason: str) -> BusinessState:
            return BusinessState(status, None, None, diagnostic=reason)

        if any(r.status == RecognitionStatus.ERROR for r in batch.results):
            return failed(RecognitionStatus.ERROR, "native_or_resource_error")
        if any(r.status == RecognitionStatus.AMBIGUOUS for r in batch.results):
            return failed(RecognitionStatus.AMBIGUOUS, "multiple_visual_candidates")
        required = (
            "round",
            "time",
            "question",
            "score",
            "digit_A",
            "digit_B",
            "digit_C",
            "digit_D",
            "confirm",
        )
        if any(
            k not in results or results[k].status != RecognitionStatus.MATCHED for k in required
        ):
            return failed(RecognitionStatus.NOT_FOUND, "missing_quiz_field")
        try:
            text = {key: results[key].candidates[0].text for key in required[:-1]}
            for key in ("question", "digit_A", "digit_B", "digit_C", "digit_D"):
                numeric = text[key]
                templates = [results[f"{key}_tpl_{n}"] for n in range(10)]
                matched = [
                    n
                    for n, r in enumerate(templates)
                    if r.status == RecognitionStatus.MATCHED and len(r.candidates) == 1
                ]
                if len(matched) != 1 or str(matched[0]) != numeric:
                    raise ValueError("digit template/OCR conflict or nonunique template")
                winner = matched[0]
                score = templates[winner].candidates[0].score
                rival = max(
                    (
                        c.score
                        for n, r in enumerate(templates)
                        if n != winner
                        for c in r.all_candidates
                    ),
                    default=0,
                )
                if score - rival < 0.15:
                    raise ValueError("insufficient digit margin")
            mark = text["round"] or ""
            if not re.fullmatch(r"[0-9]{6,}", mark) or int(mark) <= 0:
                raise ValueError("invalid round")
            digits = [
                text[key] or "" for key in ("question", "digit_A", "digit_B", "digit_C", "digit_D")
            ]
            if not all(re.fullmatch(r"[0-9]", digit) for digit in digits):
                raise ValueError("invalid digit")
            question, *options = map(int, digits)
            if len(set(options)) != 4 or options.count(question) != 1:
                raise ValueError("inconsistent options")
            if not re.fullmatch(r"-?(0|[1-9][0-9]*)", text["score"] or ""):
                raise ValueError("invalid score")
            score = int(text["score"] or "")
            if not re.fullmatch(r"(10|[0-9])\.[0-9]", text["time"] or ""):
                raise ValueError("invalid time")
            time_left = float(text["time"] or "")
            if time_left > 10:
                raise ValueError("invalid time")
            selected = []
            targets = []
            for letter in "ABCD":
                matches = [
                    style
                    for style in ("neutral", "selected")
                    if results[f"{letter}_{style}"].status == RecognitionStatus.MATCHED
                ]
                if len(matches) != 1:
                    raise ValueError("selection style unproven")
                style = matches[0]
                if style == "selected":
                    selected.append(letter)
                targets.append(VisualTarget(f"option_{letter}", f"{letter}_{style}"))
            if len(selected) > 1:
                raise ValueError("multiple selected options")
            targets.append(VisualTarget("confirm", "confirm"))
            payload = (
                mark,
                question,
                tuple(options),
                score,
                selected[0] if selected else None,
                time_left,
            )
            return BusinessState(
                RecognitionStatus.MATCHED, payload, payload[:-1], mark, tuple(targets)
            )
        except (ValueError, KeyError, IndexError):
            return failed(RecognitionStatus.AMBIGUOUS, "inconsistent_quiz_fields")

    def format_state(self, state: BusinessState) -> str:
        if state.status != RecognitionStatus.MATCHED:
            return f"{state.status}: {state.diagnostic}; 当前分数无法识别"
        data = decode_quiz_state(state)
        choices = " ".join(f"{letter}:{n}" for letter, n in zip("ABCD", data.options, strict=True))
        return (
            f"题号 #{data.round_mark} 题目 {data.question} {choices} "
            f"分数 {data.score} 选中 {data.selected}"
        )

    def parse_command(self, text: str) -> Intent:
        if text.strip() == "?":
            return ReadIntent()
        raise ValueError("Quiz answers require guarded QuizAnswerFlow; use A/B/C/D")

    def resolve(self, intent: ActionIntent, current: BusinessState) -> str:
        raise ValueError("Quiz writes require guarded QuizAnswerFlow")

    def close(self) -> None:
        pass
