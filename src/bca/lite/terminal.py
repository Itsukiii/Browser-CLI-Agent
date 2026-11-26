"""One editable prompt; output redraw is explicitly bound to that Application."""

from __future__ import annotations

import asyncio
import unicodedata
from typing import Protocol

from prompt_toolkit import PromptSession
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.application.current import create_app_session, set_app
from prompt_toolkit.output.defaults import create_output


def safe_text(text: str, limit: int = 4096) -> str:
    result = "".join(
        c if not unicodedata.category(c).startswith("C") else f"\\u{ord(c):04x}"
        for c in text[:limit]
    )
    return result + ("... [truncated]" if len(text) > limit else "")


class Terminal(Protocol):
    async def read(self, prompt: str) -> str: ...
    async def write(self, text: str) -> None: ...


class PromptTerminal:
    def __init__(self, session: PromptSession[str] | None = None) -> None:
        self.session = session or PromptSession(output=create_output(), enable_history_search=False)
        self._output = asyncio.Lock()

    async def read(self, prompt: str) -> str:
        return await self.session.prompt_async(
            prompt, handle_sigint=False, set_exception_handler=False
        )

    async def write(self, text: str) -> None:
        async with self._output:
            # Each task receives its own AppSession. Otherwise a background
            # render during prompt startup can restore another task's app=None.
            with create_app_session(), set_app(self.session.app):
                await run_in_terminal(lambda: print(safe_text(text), flush=True))
