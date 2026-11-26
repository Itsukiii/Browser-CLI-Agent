"""Small terminal shell over the accepted Coordinator; no second action scheduler."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable

from .observation import ObservationCoordinator, VisualObservation
from .terminal import Terminal

HELP = (
    "help | ? (fresh screenshot) | click <visible-round> | stop | resume | quit; Ctrl+C/EOF exits"
)


def describe(observation: VisualObservation) -> str:
    state = observation.state
    frame = observation.source.frame.frame_id if observation.source else "none"
    return (
        f"{state.status} revision={state.interaction_revision} expired={observation.expired} "
        f"frame={frame} diagnostic={state.diagnostic or 'none'}"
    )


async def interact(
    coordinator: ObservationCoordinator, terminal: Terminal, connected: Callable[[], bool]
) -> None:
    active: asyncio.Task[None] | None = None
    done = asyncio.Event()
    logs: deque[str] = deque(maxlen=16)

    class LogHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            logs.append(f"{record.levelname}: {record.getMessage()}")

    logger = logging.getLogger()
    previous_handlers = logger.handlers[:]

    async def command(text: str) -> None:
        try:
            if text == "stop":
                await coordinator.stop()
                await terminal.write("Stopped; resources retained. Use resume.")
            elif text == "resume":
                await coordinator.start()
                await terminal.write("Observation resumed.")
            else:
                result = await coordinator.execute_text(text)
                await terminal.write(f"Result: {result.outcome} {describe(result.observation)}")
                if result.outcome == "unknown":
                    await terminal.write(
                        "Input unknown; session retired, no replay. Exit required."
                    )
        except (ValueError, RuntimeError) as exc:
            await terminal.write(f"Rejected: {type(exc).__name__}: {exc}")

    async def read() -> None:
        nonlocal active
        try:
            while True:
                try:
                    text = (await terminal.read("bca-lite> ")).strip()
                except (EOFError, KeyboardInterrupt):
                    return
                if text in ("quit", "exit"):
                    return
                if not text:
                    continue
                if len(text) > 1024:
                    await terminal.write("Rejected: command exceeds 1024 characters.")
                elif text == "help":
                    await terminal.write(HELP)
                elif active is not None and not active.done():
                    await terminal.write(
                        "Busy: command rejected, not queued; submit again after result."
                    )
                else:
                    if active is not None:
                        await active  # Surface unexpected terminal/plugin errors.
                    active = asyncio.create_task(command(text))
        finally:
            done.set()

    async def updates() -> None:
        signature: object = object()
        lost_reported = False
        while not done.is_set():
            while logs:
                await terminal.write(logs.popleft())
            change = coordinator.take_change()
            while coordinator.take_change() is not None:
                pass  # Coalesce bounded notification hints; never retain frames.
            latest = coordinator.latest
            if change is not None and latest is not None:
                key = (
                    latest.state.status,
                    latest.state.signature,
                    latest.state.diagnostic,
                    latest.expired,
                )
                if key != signature:
                    await terminal.write("State: " + describe(latest))
                    signature = key
            if not connected() and not lost_reported:
                await terminal.write(
                    "Target/transport lost or session retired; no reconnect/replay."
                )
                lost_reported = True
            if active is not None and active.done():
                await active
            await asyncio.sleep(0.1)

    await terminal.write(HELP)
    logger.handlers = [LogHandler()]
    tasks = [asyncio.create_task(read()), asyncio.create_task(updates())]
    try:
        finished, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in finished:
            await task
    finally:
        done.set()
        for task in tasks:
            task.cancel()
        if active is not None:
            active.cancel()  # Coordinator drains native work before propagation.
            tasks.append(active)
        draining = asyncio.gather(*tasks, return_exceptions=True)
        while not draining.done():
            try:
                await asyncio.shield(draining)
            except asyncio.CancelledError:
                continue
        logger.handlers = previous_handlers
