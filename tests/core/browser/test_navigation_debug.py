import asyncio
import json
import re
from urllib.parse import unquote, urlsplit

import pytest

from examples.navigation_debug import FINAL_TITLE, INITIAL_TITLE, classify, local_pages, run_case

from .mock_cdp import MockCDP


class NavigationPeer(MockCDP):
    """Exercise the diagnostic against real transport/cache paths, not just canned reports."""

    def __init__(self, behavior, initial="ready"):
        super().__init__()
        self.behavior = behavior
        self.initial = initial
        self.documents = {}
        self.closed_targets = []

    async def _reply(self, socket, request):
        method, params = request["method"], request.get("params", {})
        if method == "Target.createTarget":
            url = params["url"]
            match = re.search(r"<title>(.*?)</title>", unquote(url))
            title = match[1] if match else INITIAL_TITLE
            self.targets["diagnostic"] = {
                "targetId": "diagnostic",
                "title": "temporary title" if self.initial == "cache_stale" else title,
                "url": url,
                "type": "page",
            }
            self.documents["diagnostic"] = {"title": title, "href": url, "readyState": "complete"}
            result = {"targetId": "diagnostic"}
        elif method == "Page.enable":
            # Binding already captured the temporary metadata. Queries now see the final
            # title, but no final-title event is delivered, as in the user's first report.
            if self.initial == "cache_stale":
                self.targets["diagnostic"]["title"] = INITIAL_TITLE
            elif self.initial == "document_wrong":
                self.documents["diagnostic"]["href"] = "about:blank"
            elif self.initial == "target_wrong":
                self.targets["diagnostic"]["url"] = "about:blank"
            result = {}
        elif method == "Target.getTargetInfo":
            result = {"targetInfo": self.targets[params["targetId"]]}
        elif method == "Runtime.evaluate":
            _, target_id = self.sessions[request["sessionId"]]
            result = {"result": {"type": "object", "value": self.documents[target_id]}}
        elif method == "Page.navigate":
            result = {"frameId": "frame-1", "loaderId": "loader-2"}
            if self.behavior == "failed":
                result["errorText"] = "net::ERR_ABORTED"
            elif self.behavior != "not_committed":
                self.documents["diagnostic"] = {
                    "title": FINAL_TITLE,
                    "href": params["url"],
                    "readyState": "complete",
                }
                if self.behavior != "metadata_stale":
                    self.targets["diagnostic"].update(title=FINAL_TITLE, url=params["url"])
                    if self.behavior in ("ok", "session_event"):
                        await self.emit(
                            "Target.targetInfoChanged",
                            {
                                "targetInfo": self.targets["diagnostic"],
                            },
                            request["sessionId"] if self.behavior == "session_event" else None,
                        )
        elif method == "Target.closeTarget":
            self.closed_targets.append(params["targetId"])
            self.targets.pop(params["targetId"], None)
            result = {"success": True}
        else:
            return await super()._reply(socket, request)
        response = {"id": request["id"], "result": result}
        if "sessionId" in request:
            response["sessionId"] = request["sessionId"]
        await socket.send(json.dumps(response))


@pytest.mark.parametrize(
    "behavior,expected",
    [
        ("ok", "ok"),
        ("failed", "navigation_reported_error"),
        ("not_committed", "document_navigation_not_confirmed"),
        ("metadata_stale", "target_metadata_not_updated"),
        ("no_event", "cache_stale_without_matching_event"),
        ("session_event", "cache_stale_with_session_scoped_event"),
    ],
)
def test_diagnosis_distinguishes_navigation_metadata_and_event_scope(behavior, expected):
    async def scenario():
        async with NavigationPeer(behavior) as peer:
            report = await run_case(peer.endpoint, "data", "http://127.0.0.1:1", wait=0.01)
            assert report["classification"] == expected, report
            assert (
                report["before"]["runtime"]["response"]["result"]["value"]["title"] == INITIAL_TITLE
            )
            assert report["navigation"]["response"]["frameId"] == "frame-1"
            assert len(report["samples"]) >= 2
            assert report["initial_cache_stale"] is False
            after = report["samples"][-1]
            before = report["before"]["cache"]
            assert [after["cache"][key] for key in ("page_id", "session_id", "generation")] == [
                before[key] for key in ("page_id", "session_id", "generation")
            ]
            if behavior == "session_event":
                assert report["events"][-1]["top_level_session_id"] == before["session_id"]
                assert after["cache"]["title"] == INITIAL_TITLE
                assert after["target_info"]["response"]["targetInfo"]["title"] == FINAL_TITLE
            if behavior == "no_event":
                # A late event during cleanup cannot explain an earlier stale cache sample.
                event = {
                    "elapsed": after["elapsed"] + 1,
                    "top_level_session_id": None,
                    "target_info": after["target_info"]["response"]["targetInfo"],
                }
                report["events"].append(event)
                assert classify(report) == "cache_stale_without_matching_event"
                event["elapsed"] = after["elapsed"]
                assert classify(report) == "cache_stale_despite_browser_event"
            assert peer.closed_targets == ["diagnostic"]
            assert set(peer.targets) == {"page-a", "page-b", "worker"}
            assert report["cleanup_connection"] == {
                "connected": False,
                "pending_count": 0,
                "reader_running": False,
            }

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["data", "http"])
@pytest.mark.parametrize("behavior", ["ok", "no_event", "failed"])
def test_initial_stale_cache_does_not_block_navigation(mode, behavior):
    async def scenario():
        async with NavigationPeer(behavior, initial="cache_stale") as peer:
            report = await run_case(peer.endpoint, mode, "http://127.0.0.1:12345", wait=0.01)
            assert report["initial_status"] == "ready"
            assert report["initial_cache_stale"] is True
            assert report["before"]["cache"]["title"] == "temporary title"
            assert report["initial_samples"][-1] == report["before"]
            assert "setup_error" not in report
            navigations = [r for r in peer.requests if r["method"] == "Page.navigate"]
            assert len(navigations) == 1
            assert navigations[0]["params"]["url"] == report["destination"]
            assert len(report["samples"]) >= 2
            assert (
                report["classification"]
                == {
                    "ok": "ok",
                    "no_event": "cache_stale_without_matching_event",
                    "failed": "navigation_reported_error",
                }[behavior]
            )
            before = report["before"]["cache"]
            for sample in report["samples"]:
                assert sample["cache"]["is_ready"] is True
                for key in ("page_id", "session_id", "generation"):
                    assert sample["cache"][key] == before[key]
            assert peer.closed_targets == ["diagnostic"]
            assert set(peer.targets) == {"page-a", "page-b", "worker"}
            assert report["cleanup_connection"] == {
                "connected": False,
                "pending_count": 0,
                "reader_running": False,
            }

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "initial,status",
    [
        ("document_wrong", "initial_document_not_ready"),
        ("target_wrong", "initial_target_not_ready"),
    ],
)
def test_incorrect_initial_document_or_target_stops_with_evidence(initial, status):
    async def scenario():
        async with NavigationPeer("ok", initial=initial) as peer:
            report = await run_case(peer.endpoint, "data", "http://127.0.0.1:1", wait=0.01)
            assert report["classification"] == "setup_failed"
            assert report["initial_status"] == status
            assert status in report["setup_error"]["message"]
            assert report["initial_samples"][-1] == report["before"]
            assert report["samples"] == []
            assert "navigation" not in report
            assert not any(r["method"] == "Page.navigate" for r in peer.requests)
            assert peer.closed_targets == ["diagnostic"]
            assert set(peer.targets) == {"page-a", "page-b", "worker"}

    asyncio.run(scenario())


def test_loopback_pages_are_offline_distinct_and_cleaned_up():
    async def scenario():
        async with local_pages() as origin:
            url = urlsplit(origin)
            assert url.hostname == "127.0.0.1"
            for path, title in (("/start", INITIAL_TITLE), ("/navigated", FINAL_TITLE)):
                reader, writer = await asyncio.open_connection(url.hostname, url.port)
                writer.write(f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
                await writer.drain()
                response = await reader.read()
                writer.close()
                await writer.wait_closed()
                assert response.startswith(b"HTTP/1.1 200 OK")
                assert f"<title>{title}</title>".encode() in response
        with pytest.raises(OSError):
            await asyncio.open_connection(url.hostname, url.port)

    asyncio.run(scenario())
