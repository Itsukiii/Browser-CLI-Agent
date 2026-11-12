"""Opt-in real CDP checks; only pages created by this test are navigated or closed."""

import asyncio
import os
from contextlib import suppress
from urllib.parse import quote

import pytest

from bca.core.browser import BrowserError, BrowserSession

from .mock_cdp import eventually

ENDPOINT = os.environ.get("BCA_CDP_ENDPOINT")


@pytest.mark.browser_integration
@pytest.mark.skipif(not ENDPOINT, reason="set BCA_CDP_ENDPOINT to a local test browser")
def test_real_discovery_bind_navigation_close():
    async def scenario():
        session = BrowserSession(ENDPOINT)
        created = []
        try:
            await session.connect()
            version = await session.connection.send("Browser.getVersion")
            print(f"Real browser: {version.get('product')}; CDP {version.get('protocolVersion')}")
            for title in ("BCA-01.1-A", "BCA-01.1-B"):
                result = await session.connection.send(
                    "Target.createTarget",
                    {
                        "url": "data:text/html," + quote(f"<title>{title}</title><p>{title}</p>"),
                    },
                )
                created.append(result["targetId"])
            try:
                async with asyncio.timeout(10):
                    while True:
                        targets = await session.list_targets()
                        own = [target for target in targets if target.target_id in created]
                        if len(own) == 2 and {target.title for target in own} == {
                            "BCA-01.1-A",
                            "BCA-01.1-B",
                        }:
                            break
                        await asyncio.sleep(0.05)
            except TimeoutError:
                print(f"Titles did not become ready. Last observed test targets: {own}")
                raise
            assert own[0].target_id != own[1].target_id
            for target in own:
                print(f"Test target: {target.target_id} title={target.title} url={target.url}")
            await session.bind(created[0])
            sid, generation = session.session_id, session.generation
            assert sid and session.page_id == created[0]
            print(f"Bound session: {sid} generation={generation}")
            result = await session.send("Runtime.evaluate", {"expression": "document.title"})
            assert result["result"]["value"] == "BCA-01.1-A"
            await session.send("Page.enable")
            await session.send(
                "Page.navigate",
                {
                    "url": "data:text/html," + quote("<title>BCA-01.1-Navigated</title>"),
                },
            )
            await eventually(
                lambda: (
                    session.bound_target is not None
                    and session.bound_target.title == "BCA-01.1-Navigated"
                ),
                timeout=10,
            )
            assert session.is_ready and session.session_id == sid
            assert session.generation == generation
            await session.connection.send("Target.closeTarget", {"targetId": created[0]})
            await eventually(lambda: not session.is_ready, timeout=10)
            assert session.connected and session.generation == generation + 1
            assert session.page_id is None and session.session_id is None
            print("Navigation retained binding; closing target invalidated binding")
        finally:
            try:
                for target_id in created:
                    if session.connected:
                        with suppress(BrowserError):
                            await session.connection.send(
                                "Target.closeTarget", {"targetId": target_id}
                            )
            finally:
                await session.close()
        assert session.connection.pending_count == 0
        assert not session.connection.reader_running and not session.connected
        print("Reader, pending requests and WebSocket cleaned up")

    asyncio.run(scenario())
