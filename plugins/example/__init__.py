"""Minimal plugin implementation for contract integration tests."""

from bca.core.errors import CommandError, LifecycleError
from bca.core.plugins import Plugin, PluginContext, PluginMetadata
from bca.core.protocol import Action, ActionType, Command, MouseButton, PageState
from bca.core.providers import CaptureProvider


class ExamplePlugin(Plugin):
    metadata = PluginMetadata(
        plugin_id="example", version="0.2.0", required_capabilities=("capture", "input")
    )

    def __init__(self) -> None:
        self._context: PluginContext | None = None
        self._running = False
        self._closed = False
        self._sequence = 0
        self._page_id = "demo"

    async def initialize(self, context: PluginContext) -> None:
        if self._context is not None or self._closed:
            raise LifecycleError("plugin can only be initialized once")
        for capability in self.metadata.required_capabilities:
            context.providers.get(capability)
        page_id = context.config.values.get("page_id", "demo")
        if not isinstance(page_id, str) or not page_id or any(c.isspace() for c in page_id):
            raise CommandError("page_id must be a nonempty token")
        self._page_id = page_id
        self._context = context

    async def start(self) -> None:
        if self._context is None or self._closed:
            raise LifecycleError("initialize before start; closed instances cannot restart")
        self._running = True

    def _active_context(self) -> PluginContext:
        if not self._running or self._context is None:
            raise LifecycleError("plugin is not running")
        return self._context

    async def observe(self) -> PageState:
        context = self._active_context()
        # The abstract class is a lookup token, never instantiated by the registry.
        capture = context.providers.get(CaptureProvider)  # type: ignore[type-abstract]
        frame = await capture.capture(self._page_id)
        self._sequence += 1
        return PageState(
            plugin_id=self.metadata.plugin_id,
            sequence=self._sequence,
            source_frame_id=frame.frame_id,
            data={"width": frame.width, "height": frame.height, "page_id": frame.page_id},
        )

    def parse_command(self, text: str, *, source: str = "cli") -> Command:
        parts = text.split()
        if len(parts) != 3 or parts[0] != "click":
            raise CommandError("expected: click <x> <y> (viewport CSS pixels)")
        try:
            # Validate coordinates through the same model used by the input boundary.
            action = Action(
                type=ActionType.MOUSE_CLICK,
                page_id=self._page_id,
                x=float(parts[1]),
                y=float(parts[2]),
                button=MouseButton.LEFT,
            )
        except ValueError as exc:
            raise CommandError("invalid click coordinates") from exc
        return Command(name="click", arguments={"x": action.x, "y": action.y}, source=source)

    async def handle_command(self, command: Command) -> tuple[Action, ...]:
        self._active_context()
        if command.name != "click" or set(command.arguments) != {"x", "y"}:
            raise CommandError("expected click command with x and y")
        try:
            x, y = command.arguments["x"], command.arguments["y"]
            if isinstance(x, bool) or not isinstance(x, (int, float)):
                raise ValueError("x must be numeric")
            if isinstance(y, bool) or not isinstance(y, (int, float)):
                raise ValueError("y must be numeric")
            action = Action(
                type=ActionType.MOUSE_CLICK,
                page_id=self._page_id,
                request_id=command.request_id,
                button=MouseButton.LEFT,
                x=x,
                y=y,
            )
        except ValueError as exc:
            raise CommandError("invalid click coordinates") from exc
        return (action,)

    def format_state(self, state: PageState) -> str:
        return f"{state.plugin_id} #{state.sequence}: {state.data}"

    async def stop(self) -> None:
        self._running = False

    async def close(self) -> None:
        await self.stop()
        self._context = None
        self._closed = True


def create_plugin() -> Plugin:
    return ExamplePlugin()
