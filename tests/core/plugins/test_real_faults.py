import asyncio
import os
from dataclasses import asdict

import pytest

from bca.core.runtime import ActionChannelState, BatchStatus, BrowserFreshness, EventBus, StateStore
from examples.plugin_integration import Composition, evaluate, navigate

from ..runtime.cdp_fault_proxy import ReplyLossProxy
from .real_helpers import harness, run, started, until

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(
        not os.environ.get("BCA_CDP_ENDPOINT"), reason="explicit isolated CDP required"
    ),
]


@pytest.mark.parametrize(
    "failure",
    [
        "text_timeout",
        "press_cancel",
        "release_timeout",
        "key_disconnect",
        "capture_timeout",
        "capture_close",
        "fingerprint_disconnect",
        "input_close",
        "target_during_handle",
    ],
)
def test_real_plugin_faults(failure, tmp_path):
    async def case():
        async with ReplyLossProxy(os.environ["BCA_CDP_ENDPOINT"]) as proxy:
            async with harness(tmp_path, proxy=proxy, observation_timeout=0.7) as h:
                part, session, states = h["part"], h["session"], h["states"]
                h["report"]["case"] = failure
                if failure.startswith("capture"):
                    proxy.method = "Page.captureScreenshot"
                    await part.start()
                    await proxy.seen.wait()
                    if failure == "capture_close":
                        await asyncio.gather(part.host.close(), part.host.close())
                        assert states.version == 0
                    else:
                        await until(lambda: part.controller.snapshot().observation.failed > 0)
                        await part.controller.pause()
                        assert states.version == 0
                        assert part.manager.snapshot().last_error is not None
                        proxy.method = None
                        await part.fresh()
                        assert states.version == 1
                    h["report"]["observation"] = asdict(part.controller.snapshot().observation)
                else:
                    await started(h)
                    if failure == "target_during_handle":
                        plugin = part.manager._plugin
                        original = plugin.handle_command
                        entered, release = asyncio.Event(), asyncio.Event()

                        async def handle(command):
                            actions = await original(command)
                            entered.set()
                            await release.wait()
                            return actions

                        plugin.handle_command = handle
                        task = asyncio.create_task(part.host.execute_text("click"))
                        await entered.wait()
                        await h["owner"].connection.send(
                            "Target.closeTarget", {"targetId": h["target"]}
                        )
                        await until(lambda: not session.is_ready)
                        release.set()
                        result = await task
                        assert result.status is BatchStatus.BLOCKED
                        assert not any(r["method"].startswith("Input.") for r in proxy.requests)
                    else:
                        command = "click"
                        if failure == "text_timeout":
                            await evaluate(session, "field.focus()")
                            proxy.method = "Input.insertText"
                            command = "text"
                        elif failure == "key_disconnect":
                            proxy.method, proxy.kind = "Input.dispatchKeyEvent", "keyDown"
                            command = "key"
                        elif failure == "fingerprint_disconnect":
                            proxy.method = "Page.getLayoutMetrics"
                        else:
                            proxy.method, proxy.kind = "Input.dispatchMouseEvent", "mousePressed"
                            proxy.drop_release = failure == "release_timeout"
                        task = asyncio.create_task(part.host.execute_text(command))
                        await proxy.seen.wait()
                        if failure in ("key_disconnect", "fingerprint_disconnect"):
                            await proxy.disconnect()
                        if failure == "press_cancel":
                            task.cancel()
                            with pytest.raises(asyncio.CancelledError):
                                await task
                            result = None
                            assert part.controller.snapshot().actions.cancelled == 1
                        elif failure == "input_close":
                            await asyncio.gather(part.host.close(), part.host.close())
                            outcome = (await asyncio.gather(task, return_exceptions=True))[0]
                            assert (
                                isinstance(outcome, asyncio.CancelledError)
                                or outcome.status is BatchStatus.CANCELLED
                            )
                            result = None
                            assert part.controller.snapshot().actions.cancelled == 1
                        else:
                            result = await task
                            assert result.status is BatchStatus.FAILED
                        if failure != "input_close":
                            assert part.controller.actions.state is ActionChannelState.BLOCKED
                        if failure != "fingerprint_disconnect":
                            assert h["inputs"].input_state_uncertain
                        if session.is_ready:
                            if failure == "text_timeout":
                                assert await evaluate(session, "field.value") == "probe"
                                assert (
                                    sum(r["method"] == "Input.insertText" for r in proxy.requests)
                                    == 1
                                )
                            elif failure != "input_close":
                                assert await evaluate(session, "down") == 1
                                assert any(
                                    r.get("params", {}).get("type") == "mouseReleased"
                                    for r in proxy.requests
                                )
                        if failure == "key_disconnect":
                            # Independent owner checks the real side effect after relay loss.
                            await h["owner"].bind(h["target"])
                            assert await evaluate(h["owner"], "keys") == 1
                        if failure == "fingerprint_disconnect":
                            assert not any(r["method"].startswith("Input.") for r in proxy.requests)
                    h["report"]["batch_status"] = (
                        result.status.value if result else "caller_cancelled"
                    )
                    h["report"]["channel_before_close"] = part.controller.actions.state.value
                    if result:
                        h["report"]["request_id"] = result.request_id
                        h["report"]["batch_id"] = result.batch_id
                        h["report"]["action_ids"] = [r.action_id for r in result.results]
                    if failure == "text_timeout":
                        # Retire BLOCKED composition; create an explicitly owned fresh target.
                        old_id = h["target"]
                        await part.close()
                        assert h["raw"].available and session.is_ready
                        await h["inputs"].close()
                        new_id = await h["policy"].create_recovery_target()
                        h["owned"].add(new_id)
                        assert new_id != old_id
                        await session.unbind()
                        await session.bind(new_id)
                        await navigate(session)
                        proxy.method = None
                        new_states, new_events = StateStore(), EventBus()
                        new_policy = BrowserFreshness(session, new_states)
                        new_input = new_policy.create_input_provider()
                        await new_input.start()
                        replacement = Composition(
                            session, h["raw"], new_input, new_states, new_events, new_policy
                        )
                        try:
                            assert replacement.view.get("input") is new_input
                            assert new_input is not h["inputs"]
                            await replacement.start()
                            await new_states.wait_for_update(0)
                            await replacement.controller.pause()
                            assert await evaluate(session, "hits") == 0
                            recovered = await replacement.host.execute_text("click")
                            assert recovered.status is BatchStatus.SUCCEEDED
                            await replacement.fresh()
                            assert new_states.snapshot().state.data["blue"] is True
                            assert await evaluate(session, "hits") == 1
                            assert await evaluate(session, "field.value") == ""
                            h["report"]["recovery"] = dict(
                                old_target=old_id,
                                new_target=new_id,
                                old_controller=part.controller.state.value,
                                new_status=recovered.status.value,
                                new_request_id=recovered.request_id,
                                new_version=new_states.version,
                                old_batches_replayed=0,
                            )
                        finally:
                            await replacement.close()
                            await new_input.close()
                            await new_states.close()
                            await new_events.close()
                h["report"]["dropped"] = [
                    {"method": r["method"], "kind": r.get("params", {}).get("type")}
                    for r in proxy.dropped
                ]
                assert proxy.dropped or failure == "target_during_handle"

    run(case())
