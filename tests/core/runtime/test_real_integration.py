import asyncio
import json
import os
from urllib.parse import quote

import pytest

from bca.core.browser import BrowserCaptureProvider, BrowserSession
from bca.core.protocol import Action, ActionType, MouseButton, PageState
from bca.core.runtime import (
    ActionBatch,
    ActionChannelState,
    BatchStatus,
    BrowserFreshness,
    RuntimeController,
    StateStore,
)
from examples.runtime_integration import evaluate, run_integration

from .cdp_fault_proxy import ReplyLossProxy

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(not os.environ.get("BCA_CDP_ENDPOINT"), reason="explicit test CDP required"),
]


def test_real_full_runtime_loop(tmp_path):
    report = asyncio.run(
        run_integration(os.environ["BCA_CDP_ENDPOINT"], tmp_path, samples=1, duration=0.3)
    )
    assert len(report["records"]) == 6 and report["observe_peak"] == 1
    assert report["cleanup"]["new_unfinished_tasks"] == 0


@pytest.mark.parametrize(
    "failure",
    [
        "capture_cancel",
        "action_cancel",
        "lost_text_reply",
        "release_reply_loss",
        "held_key_reply_loss",
        "disconnect",
    ],
)
def test_real_transport_faults(failure, tmp_path):
    async def run():
        baseline_tasks = asyncio.all_tasks()
        endpoint = os.environ["BCA_CDP_ENDPOINT"]
        owner = BrowserSession(endpoint)
        await owner.connect()
        original = {t.target_id for t in await owner.list_targets()}
        created = await owner.connection.send(
            "Target.createTarget",
            {
                "url": "data:text/html,"
                + quote(
                    "<input id=field autofocus><script>window.down=0;window.keys=0;"
                    "document.onmousedown=()=>down++;document.onkeydown=()=>keys++;</script>"
                )
            },
        )
        target = created["targetId"]
        report = {"evidence": "fault-injection-real-browser", "case": failure}
        try:
            async with ReplyLossProxy(endpoint) as proxy:
                session = BrowserSession(proxy.url)
                states = StateStore()
                capture = BrowserCaptureProvider(session)
                controller = provider = None
                try:
                    await session.connect()
                    await session.bind(target)
                    await session.send("Page.bringToFront")
                    async with asyncio.timeout(5):
                        while not await evaluate(session, "!!document.getElementById('field')"):
                            await asyncio.sleep(0.01)
                    await evaluate(session, "document.getElementById('field').focus()")
                    policy = BrowserFreshness(session, states)
                    provider = policy.create_input_provider(timeout=0.15)
                    await provider.start()
                    await capture.start()

                    async def observe():
                        frame = await policy.capture(capture)
                        return PageState(
                            plugin_id="fault-fixture",
                            sequence=states.version,
                            source_frame_id=frame.frame_id,
                        )

                    controller = RuntimeController(observe, provider, states, policy, interval=100)
                    if failure == "capture_cancel":
                        proxy.method = "Page.captureScreenshot"
                    await controller.start()
                    if failure == "capture_cancel":
                        await proxy.seen.wait()
                        await controller.stop()
                        assert states.version == 0
                    else:
                        await states.wait_for_update(0)
                        await controller.pause()
                        if failure == "disconnect":
                            await proxy.disconnect()
                            async with asyncio.timeout(3):
                                while session.is_ready:
                                    await asyncio.sleep(0)
                        elif failure == "lost_text_reply":
                            proxy.method = "Input.insertText"
                        elif failure == "held_key_reply_loss":
                            proxy.method, proxy.kind = "Input.dispatchKeyEvent", "keyDown"
                        else:
                            proxy.method, proxy.kind = "Input.dispatchMouseEvent", "mousePressed"
                            proxy.drop_release = failure == "release_reply_loss"
                        action = (
                            Action(page_id=target, type=ActionType.TEXT_INPUT, text="probe")
                            if failure in ("lost_text_reply", "disconnect")
                            else Action(
                                page_id=target,
                                type=ActionType.MOUSE_CLICK,
                                x=30,
                                y=15,
                                button=MouseButton.LEFT,
                            )
                        )
                        if failure == "held_key_reply_loss":
                            action = Action(page_id=target, type=ActionType.KEY_DOWN, key="a")
                        request = ActionBatch(actions=(action,), observation=controller.reference())
                        task = asyncio.create_task(controller.submit(request))
                        if failure == "action_cancel":
                            await proxy.seen.wait()
                            task.cancel()
                            with pytest.raises(asyncio.CancelledError):
                                await task
                        else:
                            result = await task
                            assert result.status in (BatchStatus.FAILED, BatchStatus.BLOCKED)
                        assert controller.actions.state is ActionChannelState.BLOCKED
                        if failure != "disconnect":
                            assert provider.input_state_uncertain
                            if failure == "lost_text_reply":
                                assert (
                                    await evaluate(
                                        session, "document.getElementById('field').value"
                                    )
                                    == "probe"
                                )
                                assert (
                                    sum(r["method"] == "Input.insertText" for r in proxy.requests)
                                    == 1
                                )
                            elif failure == "held_key_reply_loss":
                                assert await evaluate(session, "keys") == 1
                                assert any(
                                    r.get("params", {}).get("type") == "keyUp"
                                    for r in proxy.requests
                                )
                            else:
                                assert await evaluate(session, "down") == 1
                                assert any(
                                    r.get("params", {}).get("type") == "mouseReleased"
                                    for r in proxy.requests
                                )
                    report["uncertain"] = provider.input_state_uncertain
                    report["dropped_replies"] = len(proxy.dropped)
                finally:
                    if controller is not None:
                        await controller.stop()
                        await controller.stop()
                    if provider is not None:
                        await provider.close()
                    await capture.close()
                    await session.close()
                    await states.close()
                    report["pending_count"] = session.connection.pending_count
                    report["reader_running"] = session.connection.reader_running
                    report["connected"] = session.connected
                    assert session.connection.pending_count == 0
                    assert not session.connection.reader_running and not session.connected
        finally:
            await owner.connection.send("Target.closeTarget", {"targetId": target})
            try:
                async with asyncio.timeout(5):
                    while True:
                        remaining = {t.target_id for t in await owner.list_targets()}
                        if target not in remaining:
                            break
                        await asyncio.sleep(0.01)
                assert original.issubset(remaining)
            finally:
                await owner.close()
            report["new_unfinished_tasks"] = len(asyncio.all_tasks() - baseline_tasks)
            assert report["new_unfinished_tasks"] == 0
            report["owned_targets_remaining"] = 0
            report["original_targets_preserved"] = True
            (tmp_path / f"{failure}.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )

    async def bounded():
        async with asyncio.timeout(20):
            await run()

    asyncio.run(bounded())
