"""No-browser Catalog -> Loader -> Manager -> Host -> Runtime demonstration."""

import asyncio
import json
import logging
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from PIL import Image

from bca.core.plugins import (
    PluginCatalog,
    PluginConfig,
    PluginManager,
    PluginRuntimeHost,
    ProviderLookupView,
)
from bca.core.protocol import (
    Action,
    ActionResult,
    ActionStatus,
    Frame,
    ImageFormat,
    PageState,
    Viewport,
)
from bca.core.providers import CaptureProvider, InputProvider, ProviderRegistry
from bca.core.runtime import (
    ActionObservationRef,
    EventBus,
    RuntimeController,
    StateSnapshot,
    StateStore,
)


class SimulationCapture(CaptureProvider):
    def __init__(self) -> None:
        self.ready = False
        self.last_frame: Frame | None = None

    @property
    def available(self) -> bool:
        return self.ready

    async def start(self) -> None:
        self.ready = True

    async def close(self) -> None:
        self.ready = False

    async def capture(self, page_id: str) -> Frame:
        output = BytesIO()
        with Image.new("RGB", (100, 80), "red") as image:
            image.save(output, format="PNG")
        self.last_frame = Frame(
            page_id=page_id,
            width=100,
            height=80,
            data=output.getvalue(),
            format=ImageFormat.PNG,
            viewport=Viewport(width=100, height=80, capture_width=100, capture_height=80),
        )
        return self.last_frame


class SimulationInput(InputProvider):
    def __init__(self) -> None:
        self.ready = False
        self.calls: list[Action] = []

    @property
    def available(self) -> bool:
        return self.ready

    async def start(self) -> None:
        self.ready = True

    async def close(self) -> None:
        self.ready = False

    async def execute(self, action: Action) -> ActionResult:
        self.calls.append(action)
        now = datetime.now(UTC)
        return ActionResult(
            action_id=action.action_id,
            status=ActionStatus.SUCCEEDED,
            started_at=now,
            finished_at=now,
        )


class SimulationContext:
    """Fixture policy only, never use this in place of BrowserFreshness for browser input."""

    def __init__(self, states: StateStore, capture: SimulationCapture) -> None:
        self.states, self.capture = states, capture
        self.ref: ActionObservationRef | None = None

    async def begin(self) -> object:
        self.capture.last_frame = None
        return object()

    async def validate(self, token: object, state: PageState) -> bool:
        frame = self.capture.last_frame
        return frame is not None and state.source_frame_id == frame.frame_id

    def commit(self, token: object, snapshot: StateSnapshot) -> None:
        self.ref = ActionObservationRef(version=snapshot.version, token=token)

    def reference(self) -> ActionObservationRef | None:
        return self.ref

    async def check(self, reference: ActionObservationRef | None, action: Action) -> bool:
        return (
            reference is not None
            and reference is self.ref
            and reference.version == self.states.version
            and action.page_id == "demo"
        )

    async def allow_recovery(
        self,
        previous: InputProvider,
        replacement: InputProvider,
        reference: ActionObservationRef,
        blocked_reference: ActionObservationRef | None,
    ) -> bool:
        return False


async def main() -> None:
    catalog = PluginCatalog([Path(__file__).resolve().parents[1] / "plugins"])
    discovered = catalog.discover()
    capture, inputs = SimulationCapture(), SimulationInput()
    states, bus = StateStore(), EventBus()
    registry = ProviderRegistry()
    registry.register(capture)
    registry.register(inputs)
    await capture.start()
    await inputs.start()
    context = SimulationContext(states, capture)
    manager = PluginManager(
        catalog,
        providers=ProviderLookupView(registry),
        states=states,
        events=bus,
        logger=logging.getLogger("bca.example"),
    )
    manager.load("example", config=PluginConfig(values={"page_id": "demo"}))
    controller = RuntimeController(manager.observe, inputs, states, context, bus)
    host = PluginRuntimeHost(manager, controller, states)
    try:
        await host.start()
        async with asyncio.timeout(5):
            await states.wait_for_update(0)
            result = await host.execute_text("click 12 23")
        print(
            json.dumps(
                {
                    "evidence": "simulated",
                    "candidates": len(discovered.candidates),
                    "status": result.status.value,
                    "request_id": result.request_id,
                    "action_id": result.results[0].action_id,
                    "version": states.version,
                    "formatted": host.format_current_state(),
                }
            )
        )
    finally:
        await host.close()
        await inputs.close()
        await capture.close()
        await states.close()
        await bus.close()


if __name__ == "__main__":
    asyncio.run(main())
