import asyncio

import pytest

from bca.core.browser import (
    BrowserSession,
    CDPCommandError,
    CDPDisconnectedError,
    CDPTimeoutError,
    SessionState,
    TargetBindingError,
    TargetLostError,
    TargetNotFoundError,
)
from bca.core.errors import LifecycleError

from .mock_cdp import MockCDP, eventually


def test_discovery_binding_switch_and_generation():
    async def scenario():
        async with MockCDP() as peer:
            session = BrowserSession(peer.endpoint)
            assert session.state is SessionState.DISCONNECTED and session.generation == 0
            with pytest.raises(CDPDisconnectedError):
                await session.bind("page-a")
            await asyncio.gather(session.connect(), session.connect())
            assert session.generation == 1 and not session.is_ready
            assert [item.target_id for item in await session.list_targets()] == ["page-a", "page-b"]
            with pytest.raises(TargetNotFoundError):
                await session.bind("missing")
            with pytest.raises(TargetBindingError):
                await session.bind("worker")
            await asyncio.gather(session.bind("page-a"), session.bind("page-a"))
            assert session.generation == 2 and session.is_ready
            first_sid = session.session_id
            assert session.page_id == "page-a" and first_sid
            assert await session.send("Test.echo", {"value": 1}) == {"echo": {"value": 1}}
            assert peer.requests[-1]["sessionId"] == first_sid
            await session.bind("page-b")
            assert session.generation == 4
            assert session.page_id == "page-b" and session.session_id != first_sid
            assert first_sid not in peer.sessions
            await session.unbind()
            assert session.generation == 5 and session.state is SessionState.CONNECTED
            await session.unbind()
            assert session.generation == 5
            await asyncio.gather(session.close(), session.close())
            assert session.state is SessionState.CLOSED and session.generation == 6
            with pytest.raises(LifecycleError):
                await session.connect()
            await session.unbind()

    asyncio.run(scenario())


@pytest.mark.parametrize("event", ["Target.targetDestroyed", "Target.detachedFromTarget"])
def test_navigation_and_target_loss_cancel_inflight(event):
    async def scenario():
        async with MockCDP() as peer:
            session = BrowserSession(peer.endpoint)
            await session.connect()
            await session.bind("page-a")
            generation, sid = session.generation, session.session_id
            peer.targets["page-a"].update(title="Navigated", url="https://example.test/")
            await peer.emit("Target.targetInfoChanged", {"targetInfo": peer.targets["page-a"]})
            await eventually(lambda: session.bound_target.title == "Navigated")
            assert session.generation == generation and session.session_id == sid
            await peer.emit("Target.targetDestroyed", {"targetId": "page-b"})
            task = asyncio.create_task(session.send("Test.wait"))
            await peer.seen("Test.wait")
            params = {"targetId": "page-a"} if event.endswith("Destroyed") else {"sessionId": sid}
            await peer.emit(event, params)
            with pytest.raises(TargetLostError):
                await task
            assert not session.is_ready and session.connected
            assert session.generation == generation + 1
            with pytest.raises(TargetLostError):
                await session.send("Test.echo")
            peer.release_wait.set()
            await session.close()

    asyncio.run(scenario())


def test_disconnect_reconnect_never_selects_another_page():
    async def scenario():
        async with MockCDP() as peer:
            session = BrowserSession(peer.endpoint)
            await session.connect()
            await session.bind("page-a")
            old_sid = session.session_id
            with pytest.raises(CDPDisconnectedError):
                await session.send("Test.disconnect")
            assert session.state is SessionState.DISCONNECTED
            assert session.previous_target_id == "page-a"
            assert session.generation == 3
            peer.targets.pop("page-a")
            await session.connect()
            assert session.generation == 4 and not session.is_ready
            with pytest.raises(TargetNotFoundError):
                await session.bind("page-a")
            assert session.page_id is None
            await session.bind("page-b")
            assert session.session_id != old_sid and session.generation == 5
            await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["cancel", "timeout", "destroy", "detach"])
def test_attach_interruption_never_commits_stale_binding(operation):
    async def scenario():
        async with MockCDP() as peer:
            peer.attach_gate = asyncio.Event()
            session = BrowserSession(peer.endpoint, request_timeout=0.1)
            await session.connect()
            binding = asyncio.create_task(session.bind("page-a"))
            await peer.seen("Target.attachToTarget")
            if operation == "cancel":
                binding.cancel()
                error = asyncio.CancelledError
            elif operation == "timeout":
                error = CDPTimeoutError
            else:
                if operation == "destroy":
                    await peer.emit("Target.targetDestroyed", {"targetId": "page-a"})
                else:
                    await peer.emit("Target.detachedFromTarget", {"sessionId": "session-1"})
                peer.attach_gate.set()
                error = TargetLostError
            with pytest.raises(error):
                await binding
            assert not session.is_ready
            assert session.session_id is None
            await session.close()
            assert not session.connection.reader_running
            await eventually(lambda: not peer.sessions)

    asyncio.run(scenario())


def test_concurrent_bind_unbind_close_and_cancelled_close():
    async def scenario():
        async with MockCDP() as peer:
            peer.attach_gate = asyncio.Event()
            session = BrowserSession(peer.endpoint)
            await session.connect()
            binding = asyncio.create_task(session.bind("page-a"))
            await peer.seen("Target.attachToTarget")
            unbinding = asyncio.create_task(session.unbind())
            closing = asyncio.create_task(session.close())
            await asyncio.sleep(0)
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            peer.attach_gate.set()
            await binding
            await unbinding
            await asyncio.wait_for(session.close(), 2)
            assert session.state is SessionState.CLOSED
            assert session.connection.pending_count == 0
            assert not session.connection.reader_running

    asyncio.run(scenario())


def test_attach_detach_and_initialization_failures():
    async def scenario():
        async with MockCDP() as peer:
            session = BrowserSession(peer.endpoint)
            peer.fail_methods.add("Target.setDiscoverTargets")
            with pytest.raises(CDPCommandError):
                await session.connect()
            assert not session.connected
            peer.fail_methods.clear()
            await session.connect()
            peer.fail_methods.add("Target.attachToTarget")
            with pytest.raises(TargetBindingError):
                await session.bind("page-a")
            assert session.connected and not session.is_ready
            peer.fail_methods.clear()
            await session.bind("page-a")
            peer.fail_methods.add("Target.detachFromTarget")
            with pytest.raises(TargetBindingError):
                await session.unbind()
            assert not session.connected and session.session_id is None
            await session.close()

    asyncio.run(scenario())


def test_delayed_detach_from_old_attachment_does_not_invalidate_rebind():
    async def scenario():
        async with MockCDP() as peer:
            session = BrowserSession(peer.endpoint)
            await session.connect()
            await session.bind("page-a")
            old_sid = session.session_id
            await session.unbind()
            await session.bind("page-a")
            generation, sid = session.generation, session.session_id
            await peer.emit(
                "Target.detachedFromTarget", {"targetId": "page-a", "sessionId": old_sid}
            )
            await session.send("Test.echo")
            assert session.is_ready and session.session_id == sid
            assert session.generation == generation
            await session.close()

    asyncio.run(scenario())
