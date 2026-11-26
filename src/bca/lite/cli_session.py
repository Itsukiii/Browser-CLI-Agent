"""Application ownership only: explicit target -> accepted Coordinator -> ordered close."""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import ExitStack
from typing import TYPE_CHECKING
from urllib.parse import quote, urlsplit

from bca.core.browser import BrowserCaptureProvider, BrowserInputProvider, BrowserSession

from .cli_config import Settings

if TYPE_CHECKING:
    from .observation import ObservationCoordinator

# A release failure must not let Python destructors retry unknown native handles.
# The executable terminates this process with code 3; embedders must do likewise.
_RETAINED: list[object] = []


class UnreleasedNativeError(RuntimeError):
    """Dependencies retained; process termination is required, not normal loop shutdown."""


async def list_targets(settings: Settings) -> None:
    session = BrowserSession(settings.endpoint)
    try:
        await session.connect()
        for target in await session.list_targets():
            if target.type == "page":
                # Deliberately omit titles, URL paths/query and credentials.
                print(
                    json.dumps(
                        {
                            "id": target.target_id,
                            "type": target.type,
                            "host": urlsplit(target.url).hostname,
                        },
                        ensure_ascii=True,
                    )
                )
    finally:
        await session.close()


async def run(settings: Settings, *, check: bool, once: bool, create_fixture: bool) -> None:
    from .bridge import CDPBridge
    from .fixture import FixturePlugin, fixture_bundle, fixture_html
    from .observation import ObservationCoordinator
    from .vision import MaaVisionFacade
    from .vision_resources import OCRModelSpec, ResourceSpec

    stack = ExitStack()
    session = BrowserSession(settings.endpoint, request_timeout=settings.callback_timeout)
    capture, inputs = BrowserCaptureProvider(session), BrowserInputProvider(session)
    coordinator: ObservationCoordinator | None = None
    owned: str | None = None
    released = True
    try:
        bundle = stack.enter_context(fixture_bundle())
        if settings.model is None or settings.manifest is None:
            raise ValueError("fixture requires explicit --model and --manifest; no download")
        model = OCRModelSpec(settings.model, settings.manifest)
        await asyncio.to_thread(model.verify)
        plugin = FixturePlugin(ResourceSpec(bundle, model), roi=settings.roi)
        if check:
            print("Config and fixture resources valid; OCR provenance and SHA256 verified.")
            return
        terminal = None
        if not once:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise ValueError("interactive mode requires a terminal; use --once/--check")
            from .terminal import PromptTerminal

            terminal = PromptTerminal()
            # CLI owns this process. Native stdout bypasses the editable renderer;
            # normalized Coordinator/CloseReport diagnostics remain visible.
            from maa.define import LoggingLevelEnum  # type: ignore[import-untyped]
            from maa.tasker import Tasker  # type: ignore[import-untyped]

            if not await asyncio.to_thread(Tasker.set_stdout_level, LoggingLevelEnum.Off):
                raise RuntimeError("cannot configure native console logging")
        if not settings.target and not create_fixture and terminal is None:
            raise ValueError("select an exact --target from --list-targets, or --create-fixture")
        await session.connect()
        target = settings.target
        if target is None and not create_fixture and terminal is not None:
            pages = [t for t in await session.list_targets() if t.type == "page"]
            for page in pages:
                await terminal.write(f"Target {page.target_id} host={urlsplit(page.url).hostname}")
            target = (await terminal.read("Exact Target ID (blank cancels): ")).strip()
            if target not in {t.target_id for t in pages}:
                raise ValueError("no exact Target selected; no fallback")
        if create_fixture:
            result = await session.connection.send(
                "Target.createTarget",
                {"url": "data:text/html;charset=utf-8," + quote(fixture_html(bundle))},
            )
            owned = target = str(result["targetId"])
        else:
            candidates = [
                t
                for t in await session.list_targets()
                if t.type == "page" and t.target_id == target
            ]
            if len(candidates) != 1:
                raise ValueError("selected page Target no longer exists; no fallback")
        assert target is not None
        await session.bind(target)
        if owned:
            await session.send(
                "Emulation.setDeviceMetricsOverride",
                {"width": 640, "height": 400, "deviceScaleFactor": 1, "mobile": False},
            )
            await session.send("Page.bringToFront")
        await capture.start()
        await inputs.start()
        bridge = CDPBridge(
            loop=asyncio.get_running_loop(),
            session=session,
            capture=capture,
            input_provider=inputs,
            require_authorization=True,
            timeout=settings.callback_timeout,
            max_frame_age=settings.max_frame_age,
        )
        coordinator = ObservationCoordinator(
            MaaVisionFacade(bridge, plugin.resources), plugin, interval=settings.interval
        )
        await coordinator.start()
        if terminal is None:
            observation = await coordinator.refresh()
            print(f"{plugin.format_state(observation.state)} expired={observation.expired}")
        else:
            from .interactive import interact

            await terminal.write(f"Bound Target {target}; plugin=fixture roi={settings.roi}")
            await interact(coordinator, terminal, lambda: bridge.connected)
    finally:
        # Cancellation of the caller cannot unwind dependencies while native work
        # is still draining. Keep resources alive if release cannot be established.
        async def close() -> None:
            nonlocal released
            close_errors: tuple[str, ...] = ()
            if coordinator is not None:
                report = await coordinator.aclose()
                for _ in range(2):
                    if report.released or report.stop_status == "quarantined":
                        break
                    await asyncio.sleep(0.1)
                    report = await coordinator.aclose()
                released = report.released
                close_errors = report.errors
                print(f"Close: released={report.released} errors={report.errors}")
                if not released:
                    _RETAINED.extend((stack, session, capture, inputs, coordinator))
                    raise UnreleasedNativeError("native release unconfirmed; dependencies retained")
            # Once native released, each remaining owner gets a cleanup attempt
            # even if another provider/Target is already gone.
            errors = list(close_errors)
            for operation in (inputs.close, capture.close):
                try:
                    await operation()
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
            try:
                if owned and session.connected:
                    if owned in {t.target_id for t in await session.list_targets()}:
                        await session.connection.send("Target.closeTarget", {"targetId": owned})
            except Exception as exc:
                errors.append(f"Target cleanup: {type(exc).__name__}")
            finally:
                await session.close()
                stack.close()
            print(
                f"CDP closed: pending={session.connection.pending_count} "
                f"reader={session.connection.reader_running}"
            )
            if errors:
                raise RuntimeError("cleanup diagnostics: " + "; ".join(errors))

        task = asyncio.create_task(close())
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError
