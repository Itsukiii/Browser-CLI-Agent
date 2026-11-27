"""Independent evidence aggregation; does not change or select recognition results."""

import json
import sys
from collections import Counter
from pathlib import Path

from bca.lite.plugin import BusinessState
from bca.lite.quiz import decode_quiz_state
from bca.lite.vision_types import RecognitionStatus


def summarize(root):
    total = matched = wrong = valid = 0
    confusion = {key: Counter() for key in ("question", "digit_A", "digit_B", "digit_C", "digit_D")}
    groups = []
    template_confusion = {key: Counter() for key in confusion}
    frames = set()
    for path in sorted(root.glob("*/report.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        correct = 0
        for row in report["rows"]:
            total += 1
            assert row["frame_id"] not in frames
            frames.add(row["frame_id"])
            oracle = row["expected"]
            for key in confusion:
                truth = (
                    oracle["question"]
                    if key == "question"
                    else oracle["options"]["ABCD".index(key[-1])]
                )
                result = next(r for r in row["results"] if r["request_key"] == key)
                value = "|".join(c["text"] for c in result["all_candidates"]) or "missing"
                confusion[key][f"{truth}->{value}"] += 1
                hits = [
                    str(n)
                    for n in range(10)
                    if next(r for r in row["results"] if r["request_key"] == f"{key}_tpl_{n}")[
                        "status"
                    ]
                    == "MATCHED"
                ]
                template_confusion[key][f"{truth}->{','.join(hits) or 'missing'}"] += 1
            if row["state"]["status"] != "MATCHED":
                assert not row["state"]["targets"]
                continue
            matched += 1
            p = row["state"]["payload"]
            state = BusinessState(
                RecognitionStatus.MATCHED, (p[0], p[1], tuple(p[2]), p[3], p[4], p[5]), None
            )
            d = decode_quiz_state(state)
            accurate = (d.round_mark, d.question, list(d.options), d.score, d.selected) == (
                oracle["round"],
                oracle["question"],
                oracle["options"],
                int(oracle["score"]),
                None if oracle["selected"] is None else "ABCD"[oracle["selected"]],
            )
            wrong += not accurate
            correct += accurate
            valid += accurate and row["source_current"] and not row["expired"]
        groups.append(
            dict(
                group=path.parent.name,
                total=len(report["rows"]),
                correct=correct,
                close=report["close"],
                cleanup=report["cleanup"],
            )
        )
    summary = dict(
        total=total,
        matched=matched,
        wrong_matched=wrong,
        valid=valid,
        correct_rate=(matched - wrong) / total if total else 0,
        confusion=confusion,
        template_confusion=template_confusion,
        groups=groups,
    )
    (root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: v
                for k, v in summary.items()
                if k not in ("confusion", "template_confusion", "groups")
            }
        )
    )


if __name__ == "__main__":
    summarize(Path(sys.argv[1]))
