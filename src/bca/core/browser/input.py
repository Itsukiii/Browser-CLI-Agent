"""Serialized, identity-bound CDP input with bounded release and explicit uncertainty."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from bca.core.errors import CapabilityUnavailableError, LifecycleError, ValidationError
from bca.core.protocol import (
    Action,
    ActionResult,
    ActionStatus,
    ActionType,
    ErrorDetail,
    JsonObject,
    MouseButton,
)
from bca.core.protocol.validation import positive
from bca.core.providers import InputProvider

from .connection import CDPConnection
from .errors import (
    BrowserError,
    CDPCommandError,
    CDPDisconnectedError,
    TargetLostError,
)
from .geometry import measure_geometry
from .keys import Key, resolve_key
from .session import BrowserSession

logger = logging.getLogger(__name__)
type Identity = tuple[CDPConnection, str | None, str | None, int]
_BUTTONS = {MouseButton.LEFT: 1, MouseButton.RIGHT: 2, MouseButton.MIDDLE: 4}


@dataclass
class _Progress:
    stage: str = "lock"
    completed: int = 0
    attempted: bool = False
    in_flight: bool = False


class BrowserInputProvider(InputProvider):
    """One provider per session. Failed/uncertain actions must never be replayed."""

    def __init__(self, session: BrowserSession, *, timeout: float = 10.0) -> None:
        positive(timeout, "timeout")
        self._session = session
        self._timeout = timeout
        self._lock = asyncio.Lock()
        self._started = self._closed = self._uncertain = False
        self._close_task: asyncio.Task[None] | None = None
        self._owner: Identity | None = None
        self._buttons: set[MouseButton] = set()
        self._keys: dict[str, Key] = {}
        self._position = (0.0, 0.0)
        self._last_error: ErrorDetail | None = None

    @property
    def available(self) -> bool:
        return self._started and not self._closed and self._session.is_ready and not self._uncertain

    @property
    def input_state_uncertain(self) -> bool:
        return self._uncertain

    @property
    def last_error(self) -> ErrorDetail | None:
        """Sanitized failure/cancellation/cleanup diagnostic; never contains input text."""
        return self._last_error

    def _identity(self) -> Identity:
        s = self._session
        return s.connection, s.page_id, s.session_id, s.generation

    def _check(self, identity: Identity, *, cleanup: bool = False) -> None:
        if (
            not self._session.is_ready
            or identity != self._identity()
            or (self._closed and not cleanup)
        ):
            raise TargetLostError("input belongs to an unavailable or obsolete binding")

    @property
    def _modifiers(self) -> int:
        return sum(key.modifier for key in self._keys.values())

    @property
    def _button_mask(self) -> int:
        return sum(_BUTTONS[button] for button in self._buttons)

    async def start(self) -> None:
        if self._closed:
            raise LifecycleError("input provider is closed")
        if not self._session.is_ready or self._uncertain:
            raise CapabilityUnavailableError("bind a page with known input state before starting")
        self._started = True

    async def close(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close_impl(), name="bca-input-close")
        await asyncio.shield(self._close_task)

    async def _close_impl(self) -> None:
        async with self._lock:
            if self._owner is not None:
                released = await self._release(self._owner)
                if not released:
                    self._diagnostic("browser.input_cleanup", _Progress(stage="close"), False)

    def _mouse(self, kind: str, button: MouseButton | None) -> JsonObject:
        x, y = self._position
        return {
            "type": kind,
            "x": x,
            "y": y,
            "button": button.value if button else "none",
            "buttons": self._button_mask,
            "clickCount": 0 if kind == "mouseMoved" else 1,
            "modifiers": self._modifiers,
        }

    def _key_params(self, key: Key, down: bool, *, repeat: bool = False) -> JsonObject:
        text = key.text if down and not self._modifiers & (1 | 2 | 4) else ""
        return {
            "type": ("keyDown" if text else "rawKeyDown") if down else "keyUp",
            "key": key.key,
            "code": key.code,
            "windowsVirtualKeyCode": key.vk,
            "text": text,
            "unmodifiedText": text,
            "modifiers": self._modifiers,
            "autoRepeat": repeat,
            "location": 1 if key.modifier else 0,
        }

    async def _release(self, identity: Identity) -> bool:
        """At most one second in addition to action timeout; never routes to a new binding."""
        if not self._buttons and not self._keys:
            return True
        try:
            async with asyncio.timeout(1.0):
                # Release non-modifiers first, then modifiers.
                for code, key in sorted(
                    list(self._keys.items()), key=lambda pair: bool(pair[1].modifier)
                ):
                    self._check(identity, cleanup=True)
                    self._keys.pop(code)
                    try:
                        await self._session.send(
                            "Input.dispatchKeyEvent", self._key_params(key, False)
                        )
                        self._check(identity, cleanup=True)
                    except BaseException:
                        self._keys[code] = key
                        raise
                for button in list(self._buttons):
                    self._check(identity, cleanup=True)
                    self._buttons.remove(button)
                    try:
                        await self._session.send(
                            "Input.dispatchMouseEvent", self._mouse("mouseReleased", button)
                        )
                        self._check(identity, cleanup=True)
                    except BaseException:
                        self._buttons.add(button)
                        raise
            return True
        except (BrowserError, TimeoutError):
            self._uncertain = True
            return False
        except asyncio.CancelledError:
            self._uncertain = True
            raise

    def _diagnostic(self, code: str, progress: _Progress, released: bool) -> ErrorDetail:
        detail = ErrorDetail(
            code=code,
            message="Input did not complete; inspect details before further actions",
            retryable=False,
            details={
                "stage": progress.stage,
                "completed_steps": progress.completed,
                "input_attempted": progress.attempted,
                "release_confirmed": released,
                "outcome_uncertain": progress.in_flight,
                "input_state_uncertain": self._uncertain,
                "held_button_count": len(self._buttons),
                "held_key_count": len(self._keys),
            },
        )
        self._last_error = detail
        logger.warning(
            "Input failure category=%s stage=%s uncertain=%s", code, progress.stage, self._uncertain
        )
        return detail

    async def execute(self, action: Action) -> ActionResult:
        if not isinstance(action, Action):
            raise ValidationError("action must be an Action")
        if not self.available:
            raise CapabilityUnavailableError(
                "input provider is not ready or input state is uncertain"
            )
        if action.page_id != self._session.page_id:
            raise ValidationError("page_id must match the explicitly bound target")
        if action.key is not None:
            resolve_key(action.key)
        identity = self._identity()
        self._check(identity)
        started = datetime.now(UTC)
        progress = _Progress()
        acquired = False
        error: ErrorDetail | None = None
        try:
            async with asyncio.timeout(self._timeout):
                await self._lock.acquire()
                acquired = True
                self._check(identity)
                if self._uncertain:
                    raise CapabilityUnavailableError("input state is uncertain")
                if self._owner != identity and (self._buttons or self._keys):
                    self._uncertain = True
                    raise TargetLostError(
                        "held input belongs to an obsolete binding; recreate provider"
                    )
                self._owner = identity
                await self._execute(action, identity, progress)
        except BaseException as exc:
            # Validation failures have no new input effects and preserve intentional holds.
            if isinstance(exc, (ValidationError, CapabilityUnavailableError)) and not isinstance(
                exc, BrowserError
            ):
                raise
            if acquired and self._owner == identity:
                # A missing response may mean execution happened, even if release succeeds.
                if progress.in_flight and not isinstance(exc, CDPCommandError):
                    self._uncertain = True
                try:
                    released = await self._release(identity)
                except asyncio.CancelledError:
                    self._diagnostic("browser.cancelled", progress, False)
                    raise
            else:
                released = True  # Never touch another call's held state while waiting.
                if acquired and self._owner != self._identity() and (self._buttons or self._keys):
                    self._uncertain = True
                    released = False
            code = (
                "browser.cancelled"
                if isinstance(exc, asyncio.CancelledError)
                else (
                    "browser.timeout"
                    if isinstance(exc, TimeoutError)
                    else getattr(exc, "code", "browser.input")
                )
            )
            error = self._diagnostic(code, progress, released)
            if isinstance(exc, (TargetLostError, CDPDisconnectedError)):
                raise TargetLostError(
                    "input binding was lost; inspect provider.last_error"
                ) from exc
            if not isinstance(exc, (BrowserError, TimeoutError)):
                raise
        finally:
            if acquired:
                self._lock.release()
        return ActionResult(
            action_id=action.action_id,
            status=ActionStatus.FAILED if error else ActionStatus.SUCCEEDED,
            started_at=started,
            finished_at=max(started, datetime.now(UTC)),
            error=error,
        )

    async def _send(
        self, identity: Identity, progress: _Progress, method: str, params: JsonObject
    ) -> None:
        self._check(identity)
        progress.stage = str(params.get("type", method))
        progress.attempted = progress.in_flight = True
        try:
            await self._session.send(method, params)
        except CDPCommandError:
            progress.in_flight = False  # Explicit rejection, not a missing response.
            raise
        progress.in_flight = False
        progress.completed += 1
        self._check(identity)

    async def _execute(self, action: Action, identity: Identity, progress: _Progress) -> None:
        kind = action.type
        if action.x is not None:
            assert action.y is not None
            progress.stage = "geometry"
            geometry = await measure_geometry(self._session)
            self._check(identity)
            if action.x >= geometry.width or action.y >= geometry.height:
                raise ValidationError("mouse coordinates exceed the current content viewport")
            button = action.button
            if kind in (ActionType.MOUSE_DOWN, ActionType.MOUSE_CLICK) and button in self._buttons:
                raise ValidationError("mouse button is already held")
            if kind is ActionType.MOUSE_UP and button not in self._buttons:
                raise ValidationError("mouse button is not held by this provider")
            self._position = action.x, action.y
            if kind is ActionType.MOUSE_MOVE:
                await self._send(
                    identity, progress, "Input.dispatchMouseEvent", self._mouse("mouseMoved", None)
                )
                return
            assert button is not None
            if kind in (ActionType.MOUSE_DOWN, ActionType.MOUSE_CLICK):
                self._buttons.add(button)  # Pending down must also be released on cancellation.
                try:
                    await self._send(
                        identity,
                        progress,
                        "Input.dispatchMouseEvent",
                        self._mouse("mousePressed", button),
                    )
                except CDPCommandError:
                    self._buttons.remove(button)
                    raise
            if kind in (ActionType.MOUSE_UP, ActionType.MOUSE_CLICK):
                self._buttons.remove(button)
                try:
                    await self._send(
                        identity,
                        progress,
                        "Input.dispatchMouseEvent",
                        self._mouse("mouseReleased", button),
                    )
                except BaseException:
                    self._buttons.add(button)
                    raise
        elif action.key is not None:
            key = resolve_key(action.key, shift=bool(self._modifiers & 8))
            down = kind is ActionType.KEY_DOWN
            repeat = key.code in self._keys
            if not down and not repeat:
                raise ValidationError("key is not held by this provider")
            if down:
                if repeat:
                    key = self._keys[key.code]
                self._keys[key.code] = key
            else:
                key = self._keys.pop(key.code)
            try:
                await self._send(
                    identity,
                    progress,
                    "Input.dispatchKeyEvent",
                    self._key_params(key, down, repeat=down and repeat),
                )
            except CDPCommandError:
                if down and not repeat:
                    self._keys.pop(key.code)
                else:
                    self._keys[key.code] = key
                raise
            except BaseException:
                self._keys[key.code] = key
                raise
        elif action.text:
            await self._send(identity, progress, "Input.insertText", {"text": action.text})
