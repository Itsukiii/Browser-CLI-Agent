"""Read-only Browser freshness and explicit new-target recovery provenance."""

import math
from dataclasses import dataclass, field
from weakref import WeakKeyDictionary

from bca.core.browser import BrowserInputProvider, BrowserSession
from bca.core.errors import LifecycleError, ValidationError
from bca.core.protocol import Action, Frame, PageState
from bca.core.providers import CaptureProvider, InputProvider

from .action_models import ActionObservationRef
from .state_store import StateSnapshot, StateStore


@dataclass(eq=False)
class _Observation:
    fingerprint: tuple[object, ...]
    frames: set[str] = field(default_factory=set)
    valid: bool = False


class BrowserFreshness:
    """One adapter per Controller; observe must obtain its frame through capture()."""

    def __init__(self, session: BrowserSession, states: StateStore) -> None:
        self._session, self._states = session, states
        self._candidate: _Observation | None = None
        self._committed: _Observation | None = None
        self._reference: ActionObservationRef | None = None
        self._snapshot: StateSnapshot | None = None
        self._recovery_targets: set[str] = set()
        self._providers: WeakKeyDictionary[InputProvider, tuple[object, ...]] = WeakKeyDictionary()

    def _identity(self) -> tuple[object, ...]:
        if not self._session.is_ready:
            raise LifecycleError("browser binding is unavailable")
        return (
            self._session.connection,
            self._session.page_id,
            self._session.session_id,
            self._session.generation,
        )

    async def _fingerprint(self) -> tuple[object, ...]:
        identity = self._identity()
        metrics = await self._session.send("Page.getLayoutMetrics")
        measurement = await self._session.send(
            "Runtime.evaluate",
            {
                "expression": """(() => ({dpr:devicePixelRatio,x:scrollX,y:scrollY,
                surfaceWidth:innerWidth,surfaceHeight:innerHeight,
                href:location.href,timeOrigin:performance.timeOrigin}))()""",
                "returnByValue": True,
            },
        )
        remote = measurement.get("result")
        values = remote.get("value") if isinstance(remote, dict) else None
        visual, layout = metrics.get("cssVisualViewport"), metrics.get("cssLayoutViewport")
        if (
            "exceptionDetails" in measurement
            or not isinstance(values, dict)
            or not isinstance(visual, dict)
            or not isinstance(layout, dict)
        ):
            raise ValidationError("missing browser fingerprint")
        numbers: list[float] = []
        for source, keys in (
            (
                visual,
                (
                    "clientWidth",
                    "clientHeight",
                    "pageX",
                    "pageY",
                    "scale",
                    "offsetX",
                    "offsetY",
                    "zoom",
                ),
            ),
            (layout, ("clientWidth", "clientHeight", "pageX", "pageY")),
            (values, ("dpr", "x", "y", "surfaceWidth", "surfaceHeight", "timeOrigin")),
        ):
            for key in keys:
                value = source.get(key)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValidationError("invalid browser fingerprint")
                if (
                    key
                    in (
                        "clientWidth",
                        "clientHeight",
                        "scale",
                        "zoom",
                        "dpr",
                        "surfaceWidth",
                        "surfaceHeight",
                        "timeOrigin",
                    )
                    and value <= 0
                ):
                    raise ValidationError("invalid browser fingerprint extent")
                numbers.append(float(value))
        if (
            visual["scale"] != 1
            or visual["offsetX"] != 0
            or visual["offsetY"] != 0
            or abs(numbers[2] - numbers[13]) > 1e-6
            or abs(numbers[3] - numbers[14]) > 1e-6
            or abs(numbers[10] - numbers[2]) > 1
            or abs(numbers[11] - numbers[3]) > 1
            or min(numbers[0], numbers[8]) > numbers[15]
            or min(numbers[1], numbers[9]) > numbers[16]
        ):
            raise ValidationError("unsupported or changing browser geometry")
        if not isinstance(values.get("href"), str) or identity != self._identity():
            raise LifecycleError("browser identity changed during measurement")
        return (*identity, values["href"], *numbers)

    async def begin(self) -> object:
        self._candidate = None
        candidate = _Observation(await self._fingerprint())
        self._candidate = candidate
        return candidate

    async def capture(self, provider: CaptureProvider) -> Frame:
        candidate = self._candidate
        if candidate is None or candidate.valid:
            raise LifecycleError("capture requires an active observation")
        page = self._session.page_id
        if page is None:
            raise LifecycleError("browser target is missing")
        frame = await provider.capture(page)
        if (
            candidate is not self._candidate
            or frame.page_id != page
            or frame.session_id != self._session.session_id
            or candidate.fingerprint[:4] != self._identity()
        ):
            raise LifecycleError("frame binding changed")
        candidate.frames.add(frame.frame_id)
        return frame

    async def validate(self, token: object, state: PageState) -> bool:
        if not isinstance(token, _Observation) or token is not self._candidate:
            return False
        token.valid = (
            state.source_frame_id in token.frames and token.fingerprint == await self._fingerprint()
        )
        return token.valid

    def commit(self, token: object, snapshot: StateSnapshot) -> None:
        if (
            not isinstance(token, _Observation)
            or token is not self._candidate
            or not token.valid
            or snapshot is not self._states.snapshot()
            or snapshot.state.source_frame_id not in token.frames
        ):
            raise LifecycleError("observation commit lacks verified provenance")
        self._committed, self._snapshot = token, snapshot
        self._reference = ActionObservationRef(version=snapshot.version, token=object())
        self._candidate = None

    def reference(self) -> ActionObservationRef | None:
        return self._reference

    async def _current(self, reference: ActionObservationRef | None) -> bool:
        return (
            reference is not None
            and reference is self._reference
            and self._snapshot is self._states.snapshot()
            and not self._states.closed
            and self._committed is not None
            and self._committed.fingerprint == await self._fingerprint()
        )

    async def check(self, reference: ActionObservationRef | None, action: Action) -> bool:
        try:
            return await self._current(reference) and action.page_id == self._session.page_id
        except ValidationError:
            return False  # Unsupported or inconsistent geometry cannot authorize input.

    def create_input_provider(self, *, timeout: float = 10.0) -> BrowserInputProvider:
        """Caller owns start/close. Record which binding this replacement belongs to."""
        provider = BrowserInputProvider(self._session, timeout=timeout)
        self._providers[provider] = self._identity()
        return provider

    async def create_recovery_target(self) -> str:
        """Explicit opt-in: create a fresh blank target; caller owns bind and final close."""
        connection = self._session.connection
        if connection is None:
            raise LifecycleError("browser is disconnected")
        response = await connection.send("Target.createTarget", {"url": "about:blank"})
        target = response.get("targetId")
        if not isinstance(target, str):
            raise LifecycleError("browser did not create a recovery target")
        self._recovery_targets.add(target)
        return target

    async def allow_recovery(
        self,
        previous: InputProvider,
        replacement: InputProvider,
        reference: ActionObservationRef,
        blocked_reference: ActionObservationRef | None,
    ) -> bool:
        if not await self._current(reference):
            return False
        identity = self._identity()
        old_identity = self._providers.get(previous)
        # Unknown original providers cannot establish the old target: fail closed.
        if (
            old_identity is None
            or self._providers.get(replacement) != identity
            or identity[1] == old_identity[1]
            or identity[1] not in self._recovery_targets
            or (blocked_reference is not None and reference.version <= blocked_reference.version)
        ):
            return False
        self._recovery_targets.remove(str(identity[1]))
        return True
