import asyncio
import os
from pathlib import Path

import pytest

from bca.core.protocol import Action, ActionType
from bca.core.runtime import ActionBatch, BatchStatus
from examples.plugin_integration import Composition, evaluate, run_integration

from .real_helpers import harness, run, started

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(
        not os.environ.get("BCA_CDP_ENDPOINT"), reason="explicit isolated CDP required"
    ),
]


def test_real_pixel_plugin_matrix(tmp_path):
    report = asyncio.run(
        run_integration(os.environ["BCA_CDP_ENDPOINT"], tmp_path, samples=1, duration=0.3)
    )
    assert len(report["records"]) == 6
    assert report["cleanup"]["new_unfinished_tasks"] == 0


def test_real_original_example_plugin(tmp_path):
    async def case():
        async with harness(tmp_path) as h:
            await h["part"].close()
            part = Composition(
                h["session"],
                h["raw"],
                h["inputs"],
                h["states"],
                h["events"],
                h["policy"],
                root=Path(__file__).resolve().parents[3] / "plugins",
                plugin_id="example",
            )
            try:
                await part.start()
                await h["states"].wait_for_update(0)
                await part.controller.pause()
                result = await part.host.execute_text("click 80 80")
                assert result.status is BatchStatus.SUCCEEDED
                assert await evaluate(h["session"], "hits") == 1
                h["report"]["example_result"] = result.status.value
                h["report"]["request_id"] = result.request_id
                h["report"]["action_id"] = result.results[0].action_id
            finally:
                await part.close()

    run(case())


def test_old_version_waiting_batch_never_gets_new_reference(tmp_path):
    async def case():
        async with harness(tmp_path) as h:
            await started(h)
            part = h["part"]
            old = part.controller.reference()
            request = ActionBatch(
                actions=(Action(page_id=h["target"], type=ActionType.MOUSE_MOVE, x=80, y=80),),
                observation=old,
            )
            await part.fresh()
            assert part.controller.reference() is not old
            result = await part.controller.submit(request)
            assert result.status is BatchStatus.STALE and not result.results
            assert await evaluate(h["session"], "down") == 0
            h["report"].update(
                status_old=result.status.value,
                version_old=old.version,
                version_new=h["states"].version,
            )

    run(case())
