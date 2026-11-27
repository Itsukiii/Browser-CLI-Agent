"""Real Edge page logic; no claim of Maa/Quiz visual recognition at 04.1."""

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import quote

import pytest

from bca.core.browser import BrowserCaptureProvider, BrowserSession
from bca.lite.quiz_assets import quiz_bundle, quiz_html
from examples.browser_end_to_end import evaluate

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(
        not os.environ.get("BCA_CDP_ENDPOINT"), reason="explicit isolated Edge required"
    ),
]


def test_quiz_page_rounds_and_races(tmp_path):
    output = Path(os.environ.get("BCA_QUIZ_EVIDENCE", str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)

    async def run():
        session = BrowserSession(os.environ["BCA_CDP_ENDPOINT"])
        capture = BrowserCaptureProvider(session)
        target = None
        report = {"cases": []}
        await session.connect()
        original = {t.target_id for t in await session.list_targets()}
        try:
            with quiz_bundle() as bundle:
                html = quiz_html(bundle)
            target = (
                await session.connection.send(
                    "Target.createTarget",
                    {
                        "url": "data:text/html;charset=utf-8,"
                        + quote(html)
                        + "#test=1&seed=20261127"
                    },
                )
            )["targetId"]
            await session.bind(target)
            await session.send(
                "Emulation.setDeviceMetricsOverride",
                {"width": 960, "height": 640, "deviceScaleFactor": 1, "mobile": False},
            )
            await session.send("Page.bringToFront")
            async with asyncio.timeout(5):
                while not await evaluate(session, "typeof quizTest==='object'"):
                    await asyncio.sleep(0.02)
            await capture.start()
            first = await evaluate(session, "quizTest.snapshot()")
            assert first["round"] == "000001" and first["score"] == "0"
            for correct in (True, False):
                before = await evaluate(session, "quizTest.snapshot()")
                index = next(
                    i
                    for i, n in enumerate(before["options"])
                    if (n == before["question"]) == correct
                )
                await evaluate(
                    session, f"document.getElementById('option_{'ABCD'[index]}').click()"
                )
                selected = await evaluate(session, "quizTest.snapshot()")
                assert selected["score"] == before["score"] and selected["selected"] == index
                assert await evaluate(session, "document.querySelectorAll('.selected').length") == 1
                (output / f"selected-{correct}.png").write_bytes(
                    (await capture.capture(target)).data
                )
                await evaluate(session, "document.getElementById('confirm').click()")
                after = await evaluate(session, "quizTest.snapshot()")
                assert int(after["score"]) - int(before["score"]) == (1 if correct else -1)
                assert after["round"] != before["round"] and after["question"] != before["question"]
                assert after["timeLeft"] == 10
                await evaluate(session, "document.getElementById('confirm').click()")
                assert await evaluate(session, "quizTest.snapshot()") == after
                report["cases"].append(
                    {"correct": correct, "before": before, "selected": selected, "after": after}
                )
            await evaluate(
                session,
                "document.getElementById('option_A').click(); "
                "window.staleConfirm=document.getElementById('confirm').onclick",
            )
            before = await evaluate(session, "quizTest.snapshot()")
            at9999 = await evaluate(session, "quizTest.advance(9999)")
            assert at9999["round"] == before["round"]
            after = await evaluate(session, "quizTest.advance(1)")
            await evaluate(session, "staleConfirm()")
            assert await evaluate(session, "quizTest.snapshot()") == after
            assert after["score"] == before["score"] and after["selected"] is None
            report["race"] = {"before": before, "at9999": at9999, "after": after}
            for score in ("0", "-1", "-20", "-305", "12", "345", "6789"):
                await evaluate(session, f"quizTest.set({{newScore:{json.dumps(score)}}})")
                assert (
                    await evaluate(session, "document.getElementById('score').textContent") == score
                )
                (output / f"score-{score}.png").write_bytes((await capture.capture(target)).data)
            await evaluate(session, "quizTest.set({newRound:'999999'});quizTest.advance(10000)")
            assert (
                await evaluate(session, "document.getElementById('round').textContent") == "1000000"
            )
            report["events"] = await evaluate(session, "quizTest.events")
            # Real timer, not injected clock: two complete ten-second transitions.
            await session.send("Page.navigate", {"url": "about:blank"})
            await session.send(
                "Page.navigate", {"url": "data:text/html;charset=utf-8," + quote(html) + "#seed=8"}
            )
            await asyncio.sleep(0.2)
            assert await evaluate(session, "typeof quizTest") == "undefined"
            rounds = []
            for _ in range(3):
                rounds.append(
                    await evaluate(
                        session,
                        "({round:document.getElementById('round').textContent,question:document.getElementById('question').textContent,at:performance.now()})",
                    )
                )
                if len(rounds) < 3:
                    await asyncio.sleep(10.1)
            assert len({r["round"] for r in rounds}) == 3
            assert all(
                a["question"] != b["question"] for a, b in zip(rounds, rounds[1:], strict=False)
            )
            report["real_timer"] = rounds
            report["status"] = "passed"
        finally:
            await capture.close()
            if target:
                await session.connection.send("Target.closeTarget", {"targetId": target})
                async with asyncio.timeout(5):
                    while target in {t.target_id for t in await session.list_targets()}:
                        await asyncio.sleep(0.02)
            report["original_preserved"] = original.issubset(
                {t.target_id for t in await session.list_targets()}
            )
            await session.close()
            report["pending"] = session.connection.pending_count
            report["reader"] = session.connection.reader_running
            (output / "page-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            assert report["original_preserved"] and report["pending"] == 0 and not report["reader"]

    asyncio.run(run())
