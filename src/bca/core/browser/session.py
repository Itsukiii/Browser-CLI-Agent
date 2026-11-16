"""Single explicitly bound page; providers borrow this object and never close it."""

import asyncio
import logging

from bca.core.errors import LifecycleError
from bca.core.protocol import JsonObject
from bca.core.protocol.validation import token

from .connection import CDPConnection
from .errors import (
    BrowserError,
    CDPDisconnectedError,
    CDPMessageError,
    CDPTimeoutError,
    TargetLostError,
)
from .models import BrowserTarget, CDPEvent, SessionState
from .targets import TargetManager

logger = logging.getLogger(__name__)


class BrowserSession:
    def __init__(
        self,
        endpoint: str,
        *,
        connect_timeout: float = 10.0,
        request_timeout: float = 10.0,
        close_timeout: float = 2.0,
    ) -> None:
        self._endpoint = endpoint
        self._connect_timeout = connect_timeout
        self._request_timeout = request_timeout
        self._close_timeout = close_timeout
        self._connection = self._new_connection()
        self._targets = TargetManager(self._connection)
        self._lock = asyncio.Lock()
        self._refresh_lock = asyncio.Lock()
        self._metadata_revision = 0
        self._close_task: asyncio.Task[None] | None = None
        self._state = SessionState.DISCONNECTED
        self._target: BrowserTarget | None = None
        self._session_id: str | None = None
        self._generation = 0
        self._last_error: BrowserError | None = None
        self._previous_target_id: str | None = None
        self._candidate: str | None = None
        self._candidate_info: BrowserTarget | None = None
        self._candidate_invalid = False
        self._detached_during_bind: set[str] = set()
        self._watch(self._connection)

    def _new_connection(self) -> CDPConnection:
        return CDPConnection(
            connect_timeout=self._connect_timeout,
            request_timeout=self._request_timeout,
            close_timeout=self._close_timeout,
        )

    @property
    def connection(self) -> CDPConnection:
        """Borrowed browser-level transport. Its close authority remains with this session."""
        return self._connection

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def connected(self) -> bool:
        return self._connection.connected and self._state is not SessionState.CLOSED

    @property
    def is_ready(self) -> bool:
        return self.connected and self._target is not None and self._session_id is not None

    @property
    def bound_target(self) -> BrowserTarget | None:
        """Cached snapshot; use refresh_target for an explicit authoritative query."""
        return self._target

    @property
    def page_id(self) -> str | None:
        return self._target.target_id if self._target else None

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def previous_target_id(self) -> str | None:
        return self._previous_target_id

    @property
    def last_error(self) -> BrowserError | None:
        return self._last_error

    def _watch(self, connection: CDPConnection) -> None:
        connection.on_disconnect(lambda error: self._disconnected(connection, error))
        for method in (
            "Target.targetInfoChanged",
            "Target.targetDestroyed",
            "Target.detachedFromTarget",
        ):
            connection.subscribe(method, self._event)

    def _disconnected(self, connection: CDPConnection, error: BrowserError) -> None:
        if connection is not self._connection or self._state is SessionState.CLOSED:
            return
        self._last_error = error
        self._candidate_invalid = True
        if self._state is not SessionState.DISCONNECTED:
            self._generation += 1
        self._target = None
        self._session_id = None
        self._state = SessionState.DISCONNECTED
        logger.info("BrowserSession disconnected generation=%s", self._generation)

    def _invalidate_target(self, error: BrowserError | None = None) -> None:
        session_id = self._session_id
        if self._target is not None or session_id is not None:
            self._generation += 1
        self._target = None
        self._session_id = None
        self._state = SessionState.CONNECTED if self.connected else SessionState.DISCONNECTED
        self._last_error = error
        if session_id is not None:
            self._connection.invalidate_session(
                session_id, error or TargetLostError("page unbound")
            )

    def _event(self, event: CDPEvent) -> None:
        # Synchronous, no locks/await: invalidation happens in the reader's receive turn.
        params = event.params
        if event.method == "Target.targetInfoChanged":
            info = params.get("targetInfo")
            if not isinstance(info, dict):
                self._connection.abort(CDPMessageError("invalid targetInfoChanged event"))
                return
            try:
                target = BrowserTarget.from_cdp(info)
            except CDPMessageError as exc:
                self._connection.abort(exc)
                return
            if target.target_id == self._candidate:
                self._candidate_info = target
                self._candidate_invalid |= target.type != "page"
            if self._target is not None and target.target_id == self._target.target_id:
                if target.type != "page":
                    self._invalidate_target(TargetLostError("bound target is no longer a page"))
                else:
                    self._metadata_revision += 1
                    self._target = target  # Ordinary navigation does not replace the attachment.
            return
        target_id, sid = params.get("targetId"), params.get("sessionId")
        destroyed = event.method == "Target.targetDestroyed"
        if self._candidate is not None:
            if destroyed and target_id == self._candidate:
                self._candidate_invalid = True
            if not destroyed and isinstance(sid, str):
                self._detached_during_bind.add(sid)
        if (destroyed and self._target is not None and target_id == self._target.target_id) or (
            not destroyed and self._session_id is not None and sid == self._session_id
        ):
            self._invalidate_target(TargetLostError("bound target destroyed or detached"))

    def _check_open(self) -> None:
        if self._state is SessionState.CLOSED or self._close_task is not None:
            raise LifecycleError("BrowserSession is closed")

    async def connect(self) -> None:
        async with self._lock:
            self._check_open()
            if self.connected:
                return
            old = self._connection
            self._connection = self._new_connection()
            self._targets = TargetManager(self._connection)
            self._watch(self._connection)
            await old.close()
            try:
                await self._connection.connect(self._endpoint)
                await self._connection.send("Target.setDiscoverTargets", {"discover": True})
                await self._targets.list_targets()  # Fresh discovery; never auto-select a page.
                if not self._connection.connected:
                    raise CDPDisconnectedError("disconnected during browser initialization")
            except BaseException:
                await self._connection.close()
                raise
            self._generation += 1
            self._state = SessionState.CONNECTED
            self._last_error = None

    async def list_targets(self) -> tuple[BrowserTarget, ...]:
        self._check_open()
        return await self._targets.list_targets()

    async def bind(self, target_id: str) -> None:
        token(target_id, "target_id")
        async with self._lock:
            self._check_open()
            if not self.connected:
                raise CDPDisconnectedError("connect before binding a page")
            if self.is_ready and self.page_id == target_id:
                return
            await self._unbind()
            self._candidate = target_id
            self._candidate_info = None
            self._candidate_invalid = False
            self._detached_during_bind.clear()
            try:
                target, sid = await self._targets.bind(target_id)
                if (
                    not self.connected
                    or self._candidate_invalid
                    or sid in self._detached_during_bind
                ):
                    self._connection.abort(TargetLostError("target changed during attach"))
                    raise TargetLostError("target changed during attach")
                self._target = self._candidate_info or target
                self._session_id = sid
                self._previous_target_id = target_id
                self._generation += 1
                self._state = SessionState.BOUND
                self._last_error = None
            except (asyncio.CancelledError, CDPTimeoutError, CDPMessageError):
                # Attach may have succeeded remotely without returning its sessionId.
                # Dropping this connection releases all its attachments, with no retry.
                self._connection.abort(TargetLostError("attach outcome is uncertain"))
                await self._connection.close()
                raise
            finally:
                self._candidate = None
                self._candidate_info = None
                self._detached_during_bind.clear()

    async def _unbind(self) -> None:
        sid = self._session_id
        self._invalidate_target()
        if sid is None or not self.connected:
            return
        try:
            await self._targets.unbind(sid)
        except BaseException:
            # Do not leave a possibly attached orphan while allowing a new bind.
            self._connection.abort(TargetLostError("detach failed or was interrupted"))
            await self._connection.close()
            raise

    async def unbind(self) -> None:
        async with self._lock:
            if self._state is SessionState.CLOSED:
                return
            await self._unbind()

    async def send(
        self, method: str, params: JsonObject | None = None, *, timeout: float | None = None
    ) -> JsonObject:
        """Bound-page command with a generation guard for future Capture/Input providers."""
        self._check_open()
        sid, generation, connection = self._session_id, self._generation, self._connection
        if not self.is_ready or sid is None:
            raise TargetLostError("no valid page is bound")
        result = await connection.send(method, params, session_id=sid, timeout=timeout)
        if (
            not self.is_ready
            or generation != self._generation
            or sid != self._session_id
            or connection is not self._connection
        ):
            raise TargetLostError("page operation belongs to an obsolete generation")
        return result

    async def refresh_target(self) -> BrowserTarget:
        """Read current metadata without changing the binding or waiting for page load.

        Concurrent refreshes serialize. An event during a query causes a fresh read;
        the entire operation (including lock wait) uses the request timeout budget.
        """
        self._check_open()
        connection, target_id = self._connection, self.page_id
        sid, generation = self._session_id, self._generation

        def check_identity() -> None:
            if (
                not self.is_ready
                or self._close_task is not None
                or connection is not self._connection
                or target_id != self.page_id
                or sid != self._session_id
                or generation != self._generation
            ):
                raise TargetLostError("metadata query belongs to an obsolete binding")

        check_identity()
        try:
            async with asyncio.timeout(self._request_timeout):
                async with self._refresh_lock:
                    while True:
                        check_identity()
                        revision = self._metadata_revision
                        result = await connection.send(
                            "Target.getTargetInfo", {"targetId": target_id}
                        )
                        check_identity()
                        info = result.get("targetInfo")
                        if not isinstance(info, dict):
                            raise CDPMessageError("getTargetInfo returned invalid targetInfo")
                        target = BrowserTarget.from_cdp(info)
                        if target.target_id != target_id or target.type != "page":
                            raise CDPMessageError(
                                "getTargetInfo returned a different target or type"
                            )
                        if revision != self._metadata_revision:
                            continue
                        self._target = target
                        return target
        except TimeoutError as exc:
            raise CDPTimeoutError("target metadata refresh timed out") from exc

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close_impl(), name="bca-browser-close")
        await asyncio.shield(self._close_task)

    async def _close_impl(self) -> None:
        async with self._lock:
            if self._state is SessionState.CLOSED:
                return
            self._generation += 1
            self._target = None
            self._session_id = None
            self._state = SessionState.CLOSED
            # Closing the owning browser socket releases its flattened attachments.
            await self._connection.close()
