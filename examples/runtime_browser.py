"""Opt-in local CDP freshness smoke test; creates and closes only its own target."""

import asyncio
import json
import os
from urllib.parse import quote

from bca.core.browser import BrowserCaptureProvider, BrowserSession
from bca.core.protocol import Action, ActionType, JsonObject, PageState
from bca.core.runtime import (
    ActionBatch,
    BatchStatus,
    BrowserFreshness,
    RuntimeController,
    StateStore,
)


async def run_checks(endpoint: str) -> JsonObject:
    session, states = BrowserSession(endpoint), StateStore()
    await session.connect()
    connection = session.connection
    assert connection is not None
    target: str | None = None
    recovery_target: str | None = None
    controller: RuntimeController | None = None
    capture = BrowserCaptureProvider(session)
    policy = BrowserFreshness(session, states)
    provider = None
    try:
        response = await connection.send("Target.createTarget", {"url": "about:blank"})
        raw = response.get("targetId")
        assert isinstance(raw, str)
        target = raw
        await session.bind(target)
        html = "<html><body style='margin:0;height:5000px'><button>BCA 02.3</button></body></html>"
        await session.send("Page.navigate", {"url": "data:text/html," + quote(html)})
        async with asyncio.timeout(10):
            while True:
                result = await session.send(
                    "Runtime.evaluate",
                    {
                        "expression": (
                            "document.readyState === 'complete' && location.protocol === 'data:'"
                        ),
                        "returnByValue": True,
                    },
                )
                remote = result.get("result")
                if isinstance(remote, dict) and remote.get("value") is True:
                    break
                await asyncio.sleep(0.02)
        await capture.start()
        provider = policy.create_input_provider()
        await provider.start()

        async def observe() -> PageState:
            frame = await policy.capture(capture)
            return PageState(
                plugin_id="runtime-browser-smoke",
                sequence=states.version,
                source_frame_id=frame.frame_id,
            )

        controller = RuntimeController(observe, provider, states, policy, interval=100)
        await controller.start()
        async with asyncio.timeout(15):
            await states.wait_for_update(0)
        await controller.pause()
        batch = ActionBatch(
            actions=(Action(page_id=target, type=ActionType.MOUSE_MOVE, x=20, y=20),),
            observation=controller.reference(),
        )
        good = await controller.submit(batch)
        assert good.status is BatchStatus.SUCCEEDED
        await session.send(
            "Runtime.evaluate", {"expression": "scrollTo(0, 100)", "returnByValue": True}
        )
        stale = await controller.submit(batch)
        assert stale.status is BatchStatus.STALE and not stale.results
        await controller.resume()
        async with asyncio.timeout(15):
            await states.wait_for_update(1)
        await controller.pause()
        fresh = await controller.submit(
            ActionBatch(actions=batch.actions, observation=controller.reference())
        )
        assert fresh.status is BatchStatus.SUCCEEDED
        # External owner retires input, creates a clean target and obtains a new observation.
        await provider.close()
        blocked = await controller.submit(
            ActionBatch(actions=batch.actions, observation=controller.reference())
        )
        assert blocked.status is BatchStatus.BLOCKED
        recovery_target = await policy.create_recovery_target()
        await session.unbind()
        await session.bind(recovery_target)
        provider = policy.create_input_provider()
        await provider.start()
        await controller.resume()
        async with asyncio.timeout(15):
            await states.wait_for_update(2)
        await controller.pause()
        reference = controller.reference()
        assert reference is not None
        await controller.recover(provider, reference)
        recovered = await controller.submit(
            ActionBatch(
                actions=(Action(page_id=recovery_target, type=ActionType.MOUSE_MOVE, x=20, y=20),),
                observation=reference,
            )
        )
        assert recovered.status is BatchStatus.SUCCEEDED
        version = await connection.send("Browser.getVersion")
        return {
            "browser": version.get("product"),
            "initial": good.status.value,
            "after_scroll": stale.status.value,
            "after_observe": fresh.status.value,
            "state_version": states.version,
            "after_recovery": recovered.status.value,
            "owned_target": target,
        }
    finally:
        if controller is not None:
            await controller.stop()
        if provider is not None:
            await provider.close()
        await capture.close()
        for owned in (target, recovery_target):
            if owned is not None:
                await connection.send("Target.closeTarget", {"targetId": owned})
        await session.close()
        await states.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_checks(os.environ["BCA_CDP_ENDPOINT"])), indent=2))
