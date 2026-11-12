import asyncio
from http import HTTPStatus

import pytest

from bca.core.browser import (
    CDPCommandError,
    CDPConnection,
    CDPConnectionError,
    CDPDisconnectedError,
    CDPMessageError,
    CDPTimeoutError,
    EndpointError,
)
from bca.core.errors import LifecycleError, ValidationError

from .mock_cdp import MockCDP, eventually


def test_connect_discovery_concurrent_out_of_order_and_session():
    async def scenario():
        async with MockCDP() as peer:
            connection = CDPConnection()
            await asyncio.gather(
                connection.connect(peer.endpoint), connection.connect(peer.endpoint)
            )
            assert peer.discovery_paths == ["/json/version"]
            slow = asyncio.create_task(connection.send("Test.wait", {"value": "slow"}))
            fast = asyncio.create_task(
                connection.send("Test.echo", {"value": "fast"}, session_id="s")
            )
            assert (await fast)["echo"]["value"] == "fast"
            assert not slow.done()
            peer.release_wait.set()
            assert (await slow)["echo"]["value"] == "slow"
            assert [item["id"] for item in peer.requests] == [1, 2]
            assert peer.requests[1]["sessionId"] == "s"
            assert connection.pending_count == 0
            await asyncio.gather(connection.close(), connection.close())
            assert not connection.connected and not connection.reader_running
            with pytest.raises(LifecycleError):
                await connection.connect(peer.endpoint)

    asyncio.run(scenario())


def test_events_scope_unsubscribe_errors_and_reentry():
    async def scenario():
        async with MockCDP() as peer:
            connection = CDPConnection()
            await connection.connect(peer.endpoint)
            calls = []
            done = asyncio.Event()

            def broken(event):
                raise RuntimeError("callback failure")

            async def reenter(event):
                calls.append(await connection.send("Test.echo", {"event": event.method}))
                done.set()

            remove = connection.subscribe("Test.event", calls.append)
            connection.subscribe("Test.event", broken)
            connection.subscribe("Test.event", reenter, session_id="s")
            connection.subscribe("Test.event", calls.append, session_id="*")
            await peer.emit("Test.event", {"n": 1})
            await eventually(lambda: len(calls) == 2)
            remove()
            remove()
            await peer.emit("Test.event", {"n": 2}, "s")
            await asyncio.wait_for(done.wait(), 2)
            assert len(calls) == 4
            assert connection.connected
            await connection.close()

    asyncio.run(scenario())


def test_error_timeout_cancel_late_response_and_logs(caplog):
    async def scenario():
        async with MockCDP() as peer:
            connection = CDPConnection(request_timeout=0.03)
            await connection.connect(peer.endpoint)
            with pytest.raises(CDPCommandError) as caught:
                await connection.send("Test.error", {"secret": "DO_NOT_LOG_PAYLOAD"})
            assert (caught.value.method, caught.value.cdp_code, caught.value.message) == (
                "Test.error",
                -32000,
                "mock rejection",
            )
            with pytest.raises(CDPTimeoutError):
                await connection.send("Test.wait")
            assert connection.pending_count == 0
            task = asyncio.create_task(connection.send("Test.wait", timeout=1))
            await peer.seen("Test.wait", 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert connection.pending_count == 0
            peer.release_wait.set()
            assert await connection.send("Test.echo") == {"echo": {}}
            assert connection.connected
            await connection.close()

    asyncio.run(scenario())
    assert "DO_NOT_LOG_PAYLOAD" not in caplog.text


@pytest.mark.parametrize(
    "method,error",
    [
        ("Test.disconnect", CDPDisconnectedError),
        ("Test.malformed", CDPMessageError),
    ],
)
def test_reader_failure_drains_pending_once(method, error):
    async def scenario():
        async with MockCDP() as peer:
            connection = CDPConnection()
            events = []
            connection.on_disconnect(events.append)
            await connection.connect(peer.endpoint)
            pending = asyncio.create_task(connection.send("Test.wait"))
            await peer.seen("Test.wait")
            with pytest.raises(error):
                await connection.send(method)
            with pytest.raises(error):
                await pending
            assert connection.pending_count == 0
            assert len(events) == 1
            await connection.close()
            assert len(events) == 1
            assert not connection.reader_running

    asyncio.run(scenario())


def test_async_callback_failure_and_close_from_callback():
    async def scenario():
        async with MockCDP() as peer:
            connection = CDPConnection()
            await connection.connect(peer.endpoint)
            failed = asyncio.Event()

            async def broken(event):
                failed.set()
                raise RuntimeError("async failure")

            async def close(event):
                await connection.close()

            connection.subscribe("Test.fail", broken)
            connection.subscribe("Test.close", close)
            await peer.emit("Test.fail", {})
            await asyncio.wait_for(failed.wait(), 2)
            assert await connection.send("Test.echo") == {"echo": {}}
            await peer.emit("Test.close", {})
            await eventually(lambda: not connection.connected)
            await asyncio.wait_for(connection.close(), 2)
            assert not connection.reader_running

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.com:9222",
        "http://192.168.1.1:9222",
        "https://127.0.0.1:9222",
        "http://user:password@127.0.0.1:9222",
        "http://127.0.0.1:9222/path",
        "http://127.0.0.1:9222?redirect=x",
        "http://127.0.0.1:0",
    ],
)
def test_reject_nonlocal_or_ambiguous_endpoint(endpoint):
    async def scenario():
        connection = CDPConnection(connect_timeout=0.2)
        with pytest.raises(EndpointError):
            await connection.connect(endpoint)
        assert not connection.connected
        await connection.close()
        await connection.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"webSocketDebuggerUrl": "ws://example.com/devtools/browser/a"},
        {"webSocketDebuggerUrl": "ws://127.0.0.2:9222/devtools/browser/a"},
        {"webSocketDebuggerUrl": "ws://localhost:1/devtools/browser/a"},
        {"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/a"},
    ],
)
def test_reject_untrusted_discovery(document):
    async def scenario():
        async with MockCDP() as peer:
            peer.version_document = document
            connection = CDPConnection()
            with pytest.raises(EndpointError):
                await connection.connect(peer.endpoint)
            assert not connection.reader_running
            await connection.close()

    asyncio.run(scenario())


def test_http_timeout_redirect_and_retry_after_partial_failure():
    async def scenario():
        async with MockCDP() as peer:
            connection = CDPConnection(connect_timeout=0.03)
            peer.http_delay = 0.08
            with pytest.raises(CDPTimeoutError):
                await connection.connect(peer.endpoint)
            peer.http_delay = 0
            peer.http_status = HTTPStatus.FOUND
            with pytest.raises(EndpointError):
                await connection.connect(peer.endpoint)
            peer.http_status = HTTPStatus.OK
            await connection.connect(peer.endpoint)
            assert connection.connected
            await connection.close()

    asyncio.run(scenario())


def test_request_validation_and_disconnected_send():
    async def scenario():
        connection = CDPConnection()
        with pytest.raises(CDPDisconnectedError):
            await connection.send("Test.echo")
        for kwargs in (
            {"method": ""},
            {"method": "x", "params": {"x": object()}},
            {"method": "x", "timeout": 0},
            {"method": "x", "session_id": ""},
        ):
            with pytest.raises(ValidationError):
                await connection.send(**kwargs)
        await connection.close()

    asyncio.run(scenario())


def test_websocket_redirect_does_not_leave_validated_origin():
    async def scenario():
        async with MockCDP() as peer, MockCDP() as other:
            peer.websocket_redirect = other.ws_url
            connection = CDPConnection()
            with pytest.raises(CDPConnectionError):
                await connection.connect(peer.endpoint)
            assert not other.connections
            await connection.close()

    asyncio.run(scenario())


def test_waiting_send_lock_timeout_and_async_disconnect_cleanup():
    async def scenario():
        async with MockCDP() as peer:
            connection = CDPConnection()
            await connection.connect(peer.endpoint)
            notified = []

            async def disconnected(error):
                await asyncio.sleep(0)
                notified.append(error)

            connection.on_disconnect(disconnected)
            async with connection._send_lock:
                with pytest.raises(CDPTimeoutError):
                    await connection.send("Test.echo", timeout=0.01)
            assert not peer.requests and connection.pending_count == 0
            assert connection.connected
            await connection.close()
            assert len(notified) == 1
            assert not connection._callbacks

    asyncio.run(scenario())


def test_direct_connection_reconnect_after_remote_loss():
    async def scenario():
        async with MockCDP() as peer:
            connection = CDPConnection()
            await connection.connect(peer.endpoint)
            with pytest.raises(CDPDisconnectedError):
                await connection.send("Test.disconnect")
            await connection.connect(peer.endpoint)
            await connection.send("Test.echo")
            assert [item["id"] for item in peer.requests] == [1, 2]
            assert len(peer.discovery_paths) == 2
            await connection.close()

    asyncio.run(scenario())


def test_localhost_resolved_remote_is_rejected(monkeypatch):
    async def scenario():
        async def malicious_dns(*args, **kwargs):
            return [(2, 1, 6, "", ("192.0.2.1", 9222))]

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", malicious_dns)
        connection = CDPConnection()
        with pytest.raises(EndpointError):
            await connection.connect("http://localhost:9222")
        await connection.close()

    asyncio.run(scenario())
