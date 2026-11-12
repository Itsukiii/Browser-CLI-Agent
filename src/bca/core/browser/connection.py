"""One-reader CDP transport with concurrent requests and isolated event handlers."""

import asyncio
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from bca.core.errors import LifecycleError, ValidationError
from bca.core.protocol import JsonObject
from bca.core.protocol.validation import json_object, positive, token

from .endpoint import discover_websocket
from .errors import (
    BrowserError,
    CDPCommandError,
    CDPConnectionError,
    CDPDisconnectedError,
    CDPMessageError,
    CDPTimeoutError,
)
from .models import CDPEvent

type EventHandler = Callable[[CDPEvent], Awaitable[None] | None]
type DisconnectHandler = Callable[[BrowserError], Awaitable[None] | None]

logger = logging.getLogger(__name__)


class _LocalConnect(connect):
    """websockets 15 follows redirects by default; never leave the validated endpoint."""

    def process_redirect(self, exc: Exception) -> Exception:
        return exc


@dataclass
class _Pending:
    method: str
    session_id: str | None
    future: asyncio.Future[JsonObject]


class CDPConnection:
    """Single-event-loop client. Explicit close is terminal; network loss is recoverable."""

    def __init__(
        self,
        *,
        connect_timeout: float = 10.0,
        request_timeout: float = 10.0,
        close_timeout: float = 2.0,
        max_message_size: int = 16 * 1024 * 1024,
    ) -> None:
        for name, value in (
            ("connect_timeout", connect_timeout),
            ("request_timeout", request_timeout),
            ("close_timeout", close_timeout),
        ):
            positive(value, name)
        positive(max_message_size, "max_message_size", integer=True)
        self._connect_timeout = connect_timeout
        self._request_timeout = request_timeout
        self._close_timeout = close_timeout
        self._max_size = max_message_size
        self._lifecycle = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._socket: ClientConnection | None = None
        self._reader: asyncio.Task[None] | None = None
        self._callbacks: set[asyncio.Future[None]] = set()
        self._pending: dict[int, _Pending] = {}
        self._handlers: dict[int, tuple[str, str | None, EventHandler]] = {}
        self._disconnect_handlers: dict[int, DisconnectHandler] = {}
        self._next_id = 0
        self._next_handler = 0
        self._connected = False
        self._closed = False
        self._endpoint: str | None = None
        self._last_error: BrowserError | None = None
        self._close_task: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def reader_running(self) -> bool:
        return self._reader is not None and not self._reader.done()

    @property
    def last_error(self) -> BrowserError | None:
        return self._last_error

    def subscribe(
        self, method: str, handler: EventHandler, *, session_id: str | None = None
    ) -> Callable[[], None]:
        """None selects browser events; '*' selects every session. Returns an unsubscribe."""
        if self._closed:
            raise LifecycleError("connection is closed")
        token(method, "method")
        if session_id is not None:
            token(session_id, "session_id")
        self._next_handler += 1
        key = self._next_handler
        self._handlers[key] = (method, session_id, handler)
        return lambda: self._handlers.pop(key, None) and None

    def on_disconnect(self, handler: DisconnectHandler) -> Callable[[], None]:
        if self._closed:
            raise LifecycleError("connection is closed")
        self._next_handler += 1
        key = self._next_handler
        self._disconnect_handlers[key] = handler
        return lambda: self._disconnect_handlers.pop(key, None) and None

    async def connect(self, endpoint: str) -> None:
        async with self._lifecycle:
            if self._closed or self._close_task is not None:
                raise LifecycleError("closed connection cannot reconnect")
            if self.connected:
                if endpoint != self._endpoint:
                    raise LifecycleError("close before changing connection endpoint")
                return
            await self._dispose()
            try:
                async with asyncio.timeout(self._connect_timeout):
                    url = await discover_websocket(endpoint)
                    self._socket = await _LocalConnect(
                        url,
                        proxy=None,
                        open_timeout=self._connect_timeout,
                        close_timeout=self._close_timeout,
                        max_size=self._max_size,
                        compression=None,
                    )
                self._endpoint = endpoint
                self._last_error = None
                self._connected = True
                self._reader = asyncio.create_task(self._read(self._socket), name="bca-cdp-reader")
                logger.info("CDP connected")
            except TimeoutError as exc:
                await self._dispose()
                raise CDPTimeoutError("CDP discovery/connect timed out") from exc
            except (OSError, WebSocketException) as exc:
                await self._dispose()
                raise CDPConnectionError("CDP connection failed") from exc
            except BaseException:
                await self._dispose()
                raise

    async def send(
        self,
        method: str,
        params: JsonObject | None = None,
        *,
        session_id: str | None = None,
        timeout: float | None = None,
    ) -> JsonObject:
        token(method, "method")
        if session_id is not None:
            token(session_id, "session_id")
        payload = {} if params is None else params
        json_object(payload, "params")
        duration = self._request_timeout if timeout is None else timeout
        positive(duration, "timeout")
        request_id: int | None = None
        future: asyncio.Future[JsonObject] | None = None
        send_started = sent = False
        started = monotonic()
        try:
            async with asyncio.timeout(duration):
                async with self._send_lock:
                    socket = self._socket
                    if not self.connected or socket is None:
                        raise CDPDisconnectedError("CDP is not connected")
                    self._next_id += 1
                    request_id = self._next_id
                    future = asyncio.get_running_loop().create_future()
                    self._pending[request_id] = _Pending(method, session_id, future)
                    message: JsonObject = {"id": request_id, "method": method, "params": payload}
                    if session_id is not None:
                        message["sessionId"] = session_id
                    send_started = True
                    await socket.send(json.dumps(message, allow_nan=False, separators=(",", ":")))
                    sent = True
                return await future
        except TimeoutError as exc:
            if send_started and not sent:
                self.abort(CDPDisconnectedError("interrupted socket send"))
            logger.warning("CDP timeout id=%s method=%s session=%s", request_id, method, session_id)
            raise CDPTimeoutError(f"CDP request timed out: {method}") from exc
        except asyncio.CancelledError:
            if send_started and not sent:
                self.abort(CDPDisconnectedError("cancelled socket send"))
            raise
        except (OSError, WebSocketException) as exc:
            error = CDPDisconnectedError("CDP socket send failed")
            self.abort(error)
            raise error from exc
        finally:
            if request_id is not None:
                self._pending.pop(request_id, None)
            if future is not None:
                if not future.done():
                    future.cancel()
                elif not future.cancelled():
                    future.exception()  # Observe errors if failure happened before awaiting it.
            logger.debug(
                "CDP request id=%s method=%s session=%s elapsed=%.6f",
                request_id,
                method,
                session_id,
                monotonic() - started,
            )

    def invalidate_session(self, session_id: str, error: BrowserError) -> None:
        for key, pending in tuple(self._pending.items()):
            if pending.session_id == session_id:
                self._pending.pop(key, None)
                if not pending.future.done():
                    pending.future.set_exception(error)

    def abort(self, error: BrowserError) -> None:
        """Immediately invalidate and interrupt the socket; close() still owns final cleanup."""
        self._invalidate(error)
        if self._socket is not None:
            self._socket.transport.abort()

    def _invalidate(self, error: BrowserError, *, notify: bool = True) -> bool:
        if not self._connected:
            return False
        self._connected = False
        self._last_error = error
        for pending in self._pending.values():
            if not pending.future.done():
                pending.future.set_exception(error)
        self._pending.clear()
        logger.info("CDP invalidated category=%s", error.code)
        if notify:
            self._notify_disconnect(error)
        return True

    def _notify_disconnect(self, error: BrowserError) -> None:
        for handler in tuple(self._disconnect_handlers.values()):
            try:
                self._schedule(handler(error))
            except Exception:
                logger.warning("CDP disconnect handler failed")

    def _schedule(self, result: Awaitable[None] | None) -> None:
        if inspect.isawaitable(result):
            if len(self._callbacks) >= 256:
                if inspect.iscoroutine(result):
                    result.close()
                elif isinstance(result, asyncio.Future):
                    result.cancel()
                self.abort(CDPMessageError("too many unfinished event callbacks"))
                return
            # Let the Task own the coroutine directly so cancellation before its
            # first step doesn't leave a nested coroutine unawaited.
            task = asyncio.ensure_future(result)
            if isinstance(task, asyncio.Task):
                task.set_name("bca-cdp-callback")
            self._callbacks.add(task)
            task.add_done_callback(self._callback_done)

    def _callback_done(self, task: asyncio.Future[None]) -> None:
        self._callbacks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.warning("CDP async handler failed")

    def _dispatch(self, event: CDPEvent) -> None:
        for method, session_id, handler in tuple(self._handlers.values()):
            if method == event.method and (session_id == "*" or session_id == event.session_id):
                try:
                    self._schedule(handler(event))
                except Exception:
                    logger.warning("CDP event handler failed method=%s", event.method)

    async def _read(self, socket: ClientConnection) -> None:
        error: BrowserError = CDPDisconnectedError("CDP WebSocket disconnected")
        try:
            async for raw in socket:
                message = json.loads(raw)
                json_object(message, "CDP message")
                if "id" in message:
                    key = message["id"]
                    if type(key) is not int:
                        raise CDPMessageError("invalid response id")
                    pending = self._pending.get(key)
                    if pending is None or pending.future.done():
                        continue  # Timed out, cancelled, invalidated or duplicate response.
                    if message.get("sessionId") != pending.session_id:
                        raise CDPMessageError("response session does not match request")
                    if "error" in message:
                        detail = message["error"]
                        if (
                            not isinstance(detail, dict)
                            or type(detail.get("code")) is not int
                            or not isinstance(detail.get("message"), str)
                        ):
                            raise CDPMessageError("invalid CDP error response")
                        pending.future.set_exception(
                            CDPCommandError(pending.method, detail["code"], detail["message"])
                        )
                        logger.warning(
                            "CDP command failed id=%s method=%s session=%s code=%s",
                            key,
                            pending.method,
                            pending.session_id,
                            detail["code"],
                        )
                    else:
                        result = message.get("result")
                        if not isinstance(result, dict):
                            raise CDPMessageError("invalid CDP result")
                        pending.future.set_result(result)
                elif "method" in message:
                    method, params, sid = (
                        message["method"],
                        message.get("params", {}),
                        message.get("sessionId"),
                    )
                    if (
                        not isinstance(method, str)
                        or not isinstance(params, dict)
                        or (sid is not None and not isinstance(sid, str))
                    ):
                        raise CDPMessageError("invalid CDP event")
                    self._dispatch(CDPEvent(method=method, params=params, session_id=sid))
                else:
                    raise CDPMessageError("CDP message has neither id nor method")
        except asyncio.CancelledError:
            raise
        except (ValueError, ValidationError) as exc:
            error = CDPMessageError("invalid CDP JSON message")
            error.__cause__ = exc
        except BrowserError as exc:
            error = exc
        except Exception as exc:
            error = CDPDisconnectedError("CDP reader failed")
            error.__cause__ = exc
        finally:
            self._invalidate(error)
            await socket.close()

    async def _dispose(self) -> None:
        reader, socket = self._reader, self._socket
        self._reader = None
        self._socket = None
        if reader is not None and reader is not asyncio.current_task():
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        if socket is not None:
            await socket.close()
        callbacks = [task for task in self._callbacks if task is not asyncio.current_task()]
        for task in callbacks:
            task.cancel()
        await asyncio.gather(*callbacks, return_exceptions=True)

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close_impl(), name="bca-cdp-close")
        await asyncio.shield(self._close_task)

    async def _close_impl(self) -> None:
        error = CDPDisconnectedError("CDP connection closed")
        async with self._lifecycle:
            if self._closed:
                return
            self._closed = True
            changed = self._invalidate(error, notify=False)
            try:
                await self._dispose()
            finally:
                self._handlers.clear()
        # External callbacks run without holding either internal lock.
        if changed:
            self._notify_disconnect(error)
        self._disconnect_handlers.clear()
        callbacks = [task for task in self._callbacks if task is not asyncio.current_task()]
        if callbacks:
            # Give close observers a bounded chance to complete, without locks.
            await asyncio.wait(callbacks, timeout=self._close_timeout)
        for task in callbacks:
            task.cancel()
        await asyncio.gather(*callbacks, return_exceptions=True)
