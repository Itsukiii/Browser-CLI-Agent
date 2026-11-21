import asyncio
import json
import os
import sys
import threading
from dataclasses import replace

import pytest

from bca.core.errors import CommandError
from bca.core.runtime import ActionBatch, BatchStatus
from bca.plugin_sdk.vision import VisionMatchError
from examples.plugin_integration import evaluate
from examples.vision_integration import campaign, harness

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(not os.environ.get("BCA_CDP_ENDPOINT"), reason="explicit CDP required"),
]


def run(coro):
    async def bounded():
        async with asyncio.timeout(90):
            await coro

    asyncio.run(bounded())


def plugin_module():
    return next(
        module
        for name, module in sys.modules.items()
        if name.startswith("_bca_plugin_")
        and name.endswith(".plugin")
        and hasattr(module, "VisionPlugin")
    )


def test_real_dpr_region_theme_chain(tmp_path):
    run(campaign(os.environ["BCA_CDP_ENDPOINT"], tmp_path, samples=1))
    report = json.loads((tmp_path / "browser.json").read_text())
    assert report["status"] == "passed" and len(report["records"]) == 12


@pytest.mark.parametrize("mutation", ["scroll", "resize", "navigate", "rebind"])
def test_stale_and_lifecycle(mutation):
    async def case():
        async with harness(os.environ["BCA_CDP_ENDPOINT"]) as (
            session,
            raw,
            part,
            states,
            evidence,
        ):
            reference = part.controller.reference()
            command = part.manager.parse_command("click")
            actions = await part.manager.handle_command(command)
            extra = None
            try:
                if mutation == "scroll":
                    await evaluate(session, "scrollTo(50,100)")
                elif mutation == "resize":
                    await session.send(
                        "Emulation.setDeviceMetricsOverride",
                        {"width": 700, "height": 500, "deviceScaleFactor": 1, "mobile": False},
                    )
                elif mutation == "navigate":
                    await session.send("Page.reload")
                else:
                    extra = (
                        await session.connection.send("Target.createTarget", {"url": "about:blank"})
                    )["targetId"]
                    await session.bind(extra)
                await asyncio.sleep(0.1)
                result = await part.controller.submit(
                    ActionBatch(
                        actions=actions, observation=reference, request_id=command.request_id
                    )
                )
                assert result.status is BatchStatus.STALE
                if mutation in ("scroll", "resize", "navigate"):
                    await part.fresh()
                    assert (await part.host.execute_text("click")).status is BatchStatus.SUCCEEDED
                    assert await evaluate(session, "hits") == 1
            finally:
                if extra is not None:
                    await session.connection.send("Target.closeTarget", {"targetId": extra})
        assert evidence["cleanup"]["remaining_tasks"] == []

    run(case())


def test_multiple_positions_single_deterministic_click():
    async def case():
        async with harness(os.environ["BCA_CDP_ENDPOINT"]) as (
            session,
            raw,
            part,
            states,
            evidence,
        ):
            await evaluate(session, "second.style.display='block'")
            await part.fresh()
            assert states.snapshot().state.data["count"] == 2
            result = await part.host.execute_text("click")
            assert result.status is BatchStatus.SUCCEEDED and len(result.results) == 1
            assert await evaluate(session, "hits") == 1
            assert await evaluate(session, "points") == [
                [95, 81]
            ]  # MouseEvent integer CSS coordinates.

    run(case())


def test_ambiguous_rejects_command(monkeypatch):
    async def case():
        async with harness(os.environ["BCA_CDP_ENDPOINT"]) as (
            session,
            raw,
            part,
            states,
            evidence,
        ):
            module = plugin_module()
            original = module.match_frame

            def ambiguous(frame, templates, **kwargs):
                idle = next(t for t in templates if t.asset_id == "ui.idle")
                rival = replace(
                    idle,
                    asset_id="ui.rival",
                    selection=replace(idle.selection, asset_id="ui.rival"),
                )
                return original(frame, (*templates, rival), **kwargs)

            monkeypatch.setattr(module, "match_frame", ambiguous)
            await part.fresh()
            assert states.snapshot().state.data["status"] == "ambiguous"
            with pytest.raises(CommandError):
                await part.host.execute_text("click")
            assert await evaluate(session, "hits") == 0

    run(case())


def test_cancel_waits_for_native_worker(monkeypatch):
    async def case():
        async with harness(os.environ["BCA_CDP_ENDPOINT"]) as (
            session,
            raw,
            part,
            states,
            evidence,
        ):
            entered, release = threading.Event(), threading.Event()
            module = plugin_module()
            original = module.match_frame

            def blocked(*args, **kwargs):
                entered.set()
                assert release.wait(10)
                return original(*args, **kwargs)

            monkeypatch.setattr(module, "match_frame", blocked)
            await part.controller.resume()
            while not entered.is_set():
                await asyncio.sleep(0.005)
            closing = asyncio.create_task(part.close())
            try:
                await asyncio.sleep(0.05)
                assert not closing.done()
            finally:
                release.set()
            await closing
            assert not any(t.get_name() == "bca.vision.worker" for t in asyncio.all_tasks())

    run(case())


def test_match_failure_does_not_publish(monkeypatch):
    async def case():
        async with harness(os.environ["BCA_CDP_ENDPOINT"]) as (
            session,
            raw,
            part,
            states,
            evidence,
        ):
            version = states.version
            entered = threading.Event()

            def failed(*args, **kwargs):
                entered.set()
                raise VisionMatchError("injected failure")

            monkeypatch.setattr(plugin_module(), "match_frame", failed)
            await part.controller.resume()
            while not entered.is_set():
                await asyncio.sleep(0.005)
            await part.controller.pause()
            assert states.version == version

    run(case())
