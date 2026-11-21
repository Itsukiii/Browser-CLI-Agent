"""Pixels supply business state; Runtime alone authorizes and dispatches inputs."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from bca.core.errors import CommandError, LifecycleError
from bca.core.plugins import PluginContext, PluginMetadata
from bca.core.protocol import (
    Action,
    ActionType,
    Command,
    Frame,
    MouseButton,
    PageState,
    RecognitionStatus,
)
from bca.core.providers import CaptureProvider
from bca.plugin_sdk.assets import AssetStore, LoadedTemplate
from bca.plugin_sdk.vision import MatchOptions, MatchResult, MatchStatus, match_frame

from .assets import create_assets


class VisionPlugin:
    metadata = PluginMetadata(
        plugin_id="vision-fixture", version="0.2.0", required_capabilities=("capture", "input")
    )

    def __init__(self) -> None:
        self.context: PluginContext | None = None
        self.running = False
        self.sequence = 0
        self.frame: Frame | None = None
        self.result: MatchResult | None = None
        self.store: AssetStore | None = None
        self.temporary: TemporaryDirectory[str] | None = None
        self.templates: tuple[LoadedTemplate, ...] = ()
        self.worker: asyncio.Task[MatchResult] | None = None

    async def initialize(self, context: PluginContext) -> None:
        self.context = context
        self.temporary = TemporaryDirectory(prefix="bca-vision-")
        root = Path(self.temporary.name)
        create_assets(root)
        theme = context.config.values.get("theme", "light")
        if theme not in ("light", "dark"):
            raise CommandError("unsupported fixture theme")
        self.store = AssetStore(root, profile=Path(f"{theme}.ini"))
        self.templates = tuple(self.store.load(asset, scene="panel") for asset in self.store.ids())

    async def start(self) -> None:
        self.running = True

    async def _settle_worker(self) -> None:
        if self.worker is not None:
            while not self.worker.done():
                try:
                    await asyncio.shield(self.worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not self.worker.cancelled():
                self.worker.exception()
            self.worker = None

    async def observe(self) -> PageState:
        if not self.running or self.context is None or self.worker is not None:
            raise LifecycleError("fixture is inactive or observation is already running")
        self.frame = None
        self.result = None
        page = self.context.config.values["page_id"]
        assert isinstance(page, str)
        capture = self.context.providers.get(CaptureProvider)  # type: ignore[type-abstract]
        frame = await capture.capture(page)
        # Explicit fixture scales. Do not infer arbitrary CSS geometry from DPR.
        options = MatchOptions(scales=((1, 1), (1.5, 1.5), (2, 2)), max_proposals_per_variant=8)
        self.worker = asyncio.create_task(
            asyncio.to_thread(match_frame, frame, self.templates, options=options),
            name="bca.vision.worker",
        )
        try:
            result = await asyncio.shield(self.worker)
        finally:
            # Cancellation cannot kill native work. Wait before releasing owned assets.
            await self._settle_worker()
        if not self.running:
            raise LifecycleError("fixture stopped during observation")
        self.frame, self.result = frame, result
        self.sequence += 1
        first = result.matches[0] if result.status is MatchStatus.MATCHED else None
        return PageState(
            plugin_id=self.metadata.plugin_id,
            sequence=self.sequence,
            source_frame_id=frame.frame_id,
            recognition_status=RecognitionStatus.OK if first else RecognitionStatus.UNKNOWN,
            data={
                "status": result.status.value,
                "count": len(result.matches),
                "asset_id": first.asset_id if first else None,
                "variant_id": first.variant_id if first else None,
                "score": first.score if first else None,
                "x": first.center[0] if first else None,
                "y": first.center[1] if first else None,
                "vision_ms": result.timing.total_ms,
                "decode_ms": result.timing.decode_ms,
                "preprocess_ms": result.timing.preprocess_ms,
                "match_ms": result.timing.match_ms,
                "postprocess_ms": result.timing.postprocess_ms,
            },
        )

    def parse_command(self, text: str, *, source: str = "cli") -> Command:
        if text != "click":
            raise CommandError("expected click")
        return Command(name=text, source=source)

    async def handle_command(self, command: Command) -> tuple[Action, ...]:
        if (
            not self.running
            or self.frame is None
            or self.result is None
            or self.result.status is not MatchStatus.MATCHED
            or not self.result.matches
        ):
            raise CommandError("no unambiguous visual target")
        # Multiple copies are valid; deterministically choose the first SDK-sorted match.
        candidate = self.result.matches[0]
        x, y = self.frame.pixel_to_css(*candidate.center)
        return (
            Action(
                page_id=self.frame.page_id,
                request_id=command.request_id,
                type=ActionType.MOUSE_CLICK,
                button=MouseButton.LEFT,
                x=x,
                y=y,
            ),
        )

    def format_state(self, state: PageState) -> str:
        return f"{state.plugin_id} #{state.sequence}: {state.data['asset_id']}"

    async def stop(self) -> None:
        self.running = False
        await self._settle_worker()
        self.frame = None
        self.result = None

    async def close(self) -> None:
        await self.stop()
        if self.store is not None:
            self.store.close()
            self.store = None
        self.templates = ()
        if self.temporary is not None:
            self.temporary.cleanup()
            self.temporary = None
        self.context = None
