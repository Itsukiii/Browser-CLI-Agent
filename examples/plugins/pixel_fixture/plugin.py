"""PNG-only state recognition; DOM is reserved for the external test oracle."""

from io import BytesIO

from PIL import Image, ImageChops

from bca.core.errors import CommandError, LifecycleError
from bca.core.plugins import PluginContext, PluginMetadata
from bca.core.protocol import Action, ActionType, Command, Frame, MouseButton, PageState
from bca.core.providers import CaptureProvider


class PixelPlugin:
    metadata = PluginMetadata(
        plugin_id="pixel-fixture", version="0.2.0", required_capabilities=("capture", "input")
    )

    def __init__(self) -> None:
        self.context: PluginContext | None = None
        self.running = False
        self.sequence = 0
        self.frame: Frame | None = None
        self.point = (0.0, 0.0)

    async def initialize(self, context: PluginContext) -> None:
        self.context = context

    async def start(self) -> None:
        self.running = True

    async def observe(self) -> PageState:
        if not self.running or self.context is None:
            raise LifecycleError("fixture is not active")
        page = self.context.config.values["page_id"]
        assert isinstance(page, str)
        capture = self.context.providers.get(CaptureProvider)  # type: ignore[type-abstract]
        frame = await capture.capture(page)
        with Image.open(BytesIO(frame.data)) as image, image.convert("RGB") as rgb:
            channels = rgb.split()
            red, green, blue = channels
            try:
                for channel, other, selected in ((red, blue, False), (blue, red, True)):
                    with (
                        channel.point(lambda v: 255 if v > 240 else 0) as high,
                        other.point(lambda v: 255 if v < 15 else 0) as low,
                        green.point(lambda v: 255 if v < 15 else 0) as dark,
                        ImageChops.multiply(high, low) as first,
                        ImageChops.multiply(first, dark) as mask,
                    ):
                        bounds = mask.getbbox()
                    if bounds:
                        x0, y0, x1, y1 = bounds
                        self.point = frame.pixel_to_css((x0 + x1 - 1) / 2, (y0 + y1 - 1) / 2)
                        self.frame = frame
                        self.sequence += 1
                        return PageState(
                            plugin_id=self.metadata.plugin_id,
                            sequence=self.sequence,
                            source_frame_id=frame.frame_id,
                            data={
                                "x": self.point[0],
                                "y": self.point[1],
                                "blue": selected,
                                "width": frame.width,
                                "height": frame.height,
                            },
                        )
            finally:
                for channel in channels:
                    channel.close()
        raise CommandError("fixture marker missing")

    def parse_command(self, text: str, *, source: str = "cli") -> Command:
        if text not in ("click", "text", "key"):
            raise CommandError("expected fixture command")
        return Command(name=text, source=source)

    async def handle_command(self, command: Command) -> tuple[Action, ...]:
        if not self.running or self.frame is None:
            raise LifecycleError("fixture requires an observation")
        if command.name == "text":
            action = Action(
                page_id=self.frame.page_id,
                request_id=command.request_id,
                type=ActionType.TEXT_INPUT,
                text="probe",
            )
        elif command.name == "key":
            action = Action(
                page_id=self.frame.page_id,
                request_id=command.request_id,
                type=ActionType.KEY_DOWN,
                key="a",
            )
        else:
            action = Action(
                page_id=self.frame.page_id,
                request_id=command.request_id,
                type=ActionType.MOUSE_CLICK,
                x=self.point[0],
                y=self.point[1],
                button=MouseButton.LEFT,
            )
        return (action,)

    def format_state(self, state: PageState) -> str:
        return f"{state.plugin_id} #{state.sequence}: {state.data['blue']}"

    async def stop(self) -> None:
        self.running = False

    async def close(self) -> None:
        await self.stop()
        self.context = None
        self.frame = None
