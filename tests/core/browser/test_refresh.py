import asyncio
import json

import pytest

from bca.core.browser import (
    BrowserSession,
    CDPCommandError,
    CDPDisconnectedError,
    CDPMessageError,
    CDPTimeoutError,
    TargetLostError,
)
from bca.core.errors import LifecycleError

from .mock_cdp import MockCDP, eventually


class MetadataPeer(MockCDP):
    def __init__(self):
        super().__init__()
        self.gate = asyncio.Event()
        self.gate.set()
        self.invalid = None
        self.always_emit = False

    async def _reply(self, socket, request):
        if request["method"] != "Target.getTargetInfo":
            return await super()._reply(socket, request)
        target = self.targets.get(request["params"]["targetId"])
        response = {"id": request["id"]}
        if target is None or request["method"] in self.fail_methods:
            response["error"] = {"code": -32000, "message": "target unavailable"}
        else:
            response["result"] = (
                self.invalid if self.invalid is not None else {"targetInfo": dict(target)}
            )
        await self.gate.wait()
        if self.always_emit:
            await self.emit("Target.targetInfoChanged", {"targetInfo": dict(target)})
        try:
            await socket.send(json.dumps(response))
        except Exception:
            pass  # Late reply after deliberate disconnect.


def test_refresh_initial_and_navigation_without_final_title_events():
    async def scenario():
        async with MetadataPeer() as peer:
            session = BrowserSession(peer.endpoint)
            await session.connect()
            peer.targets["page-a"]["title"] = "temporary URL title"
            await session.bind("page-a")
            assert session.bound_target.title == "temporary URL title"
            identity = session.page_id, session.session_id, session.generation
            for title, url in (("Initial final", "about:blank"), ("Navigated", "about:blank#new")):
                old = session.bound_target
                peer.targets["page-a"].update(title=title, url=url)
                assert session.bound_target is old
                result = await session.refresh_target()
                assert result == session.bound_target
                assert (result.title, result.url) == (title, url)
                assert (session.page_id, session.session_id, session.generation) == identity
                assert "sessionId" not in peer.requests[-1]
            await session.close()
            assert session.connection.pending_count == 0
            assert not session.connection.reader_running

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "operation", ["unbind", "switch", "rebind", "disconnect", "close", "destroy"]
)
def test_refresh_rejects_old_binding_response(operation):
    async def scenario():
        async with MetadataPeer() as peer:
            session = BrowserSession(peer.endpoint)
            await session.connect()
            await session.bind("page-a")
            peer.gate.clear()
            task = asyncio.create_task(session.refresh_target())
            await peer.seen("Target.getTargetInfo")
            if operation == "unbind":
                await session.unbind()
            elif operation == "switch":
                await session.bind("page-b")
            elif operation == "rebind":
                await session.unbind()
                await session.bind("page-a")
            elif operation == "disconnect":
                with pytest.raises(CDPDisconnectedError):
                    await session.send("Test.disconnect")
                await session.connect()
                await session.bind("page-b")
            elif operation == "close":
                await session.close()
            else:
                await peer.emit("Target.targetDestroyed", {"targetId": "page-a"})
                await eventually(lambda: not session.is_ready)
            expected = session.bound_target
            peer.gate.set()
            with pytest.raises((TargetLostError, CDPDisconnectedError)):
                await task
            assert session.bound_target == expected
            assert session.connection.pending_count == 0
            await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"targetInfo": []},
        {"targetInfo": {"targetId": "page-a"}},
        {"targetInfo": {"targetId": "other", "title": "x", "url": "x", "type": "page"}},
        {"targetInfo": {"targetId": "page-a", "title": "x", "url": "x", "type": "worker"}},
        {"targetInfo": {"targetId": "page-a", "title": 123, "url": "x", "type": "page"}},
    ],
)
def test_refresh_invalid_response_preserves_cache(invalid):
    async def scenario():
        async with MetadataPeer() as peer:
            session = BrowserSession(peer.endpoint)
            await session.connect()
            await session.bind("page-a")
            old = session.bound_target
            peer.invalid = invalid
            with pytest.raises(CDPMessageError):
                await session.refresh_target()
            assert session.bound_target == old and session.is_ready
            assert session.connection.pending_count == 0
            await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["command", "missing", "timeout", "cancel"])
def test_refresh_failure_and_cancellation_cleanup(failure):
    async def scenario():
        async with MetadataPeer() as peer:
            session = BrowserSession(peer.endpoint, request_timeout=0.2)
            await session.connect()
            await session.bind("page-a")
            old = session.bound_target
            if failure == "command":
                peer.fail_methods.add("Target.getTargetInfo")
            elif failure == "missing":
                peer.targets.pop("page-a")
            else:
                peer.gate.clear()
            task = asyncio.create_task(session.refresh_target())
            await peer.seen("Target.getTargetInfo")
            if failure == "cancel":
                task.cancel()
            error = {
                "command": CDPCommandError,
                "missing": CDPCommandError,
                "timeout": CDPTimeoutError,
                "cancel": asyncio.CancelledError,
            }[failure]
            with pytest.raises(error):
                await task
            assert session.bound_target == old
            assert session.connection.pending_count == 0
            peer.gate.set()
            await session.close()
            assert not session.connection.reader_running

    asyncio.run(scenario())


def test_event_during_query_forces_reread_and_refreshes_serialize():
    async def scenario():
        async with MetadataPeer() as peer:
            session = BrowserSession(peer.endpoint)
            await session.connect()
            await session.bind("page-a")
            peer.gate.clear()
            first = asyncio.create_task(session.refresh_target())
            await peer.seen("Target.getTargetInfo")
            second = asyncio.create_task(session.refresh_target())
            peer.targets["page-a"].update(title="new event")
            await peer.emit("Target.targetInfoChanged", {"targetInfo": peer.targets["page-a"]})
            await eventually(lambda: session.bound_target.title == "new event")
            assert sum(r["method"] == "Target.getTargetInfo" for r in peer.requests) == 1
            peer.gate.set()
            results = await asyncio.gather(first, second)
            assert all(result.title == "new event" for result in results)
            assert session.bound_target.title == "new event"
            assert sum(r["method"] == "Target.getTargetInfo" for r in peer.requests) == 3
            await session.close()

    asyncio.run(scenario())


def test_continuous_events_are_bounded_and_unbound_closed_calls_fail():
    async def scenario():
        async with MetadataPeer() as peer:
            session = BrowserSession(peer.endpoint, request_timeout=0.1)
            with pytest.raises(TargetLostError):
                await session.refresh_target()
            await session.connect()
            await session.bind("page-a")
            peer.always_emit = True
            with pytest.raises(CDPTimeoutError):
                await session.refresh_target()
            assert session.connection.pending_count == 0
            await session.close()
            with pytest.raises(LifecycleError):
                await session.refresh_target()

    asyncio.run(scenario())
