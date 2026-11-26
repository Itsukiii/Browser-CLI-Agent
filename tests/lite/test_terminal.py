import asyncio
from types import SimpleNamespace

from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from bca.lite.interactive import interact
from bca.lite.terminal import PromptTerminal, safe_text


def test_redraw_preserves_editing_buffer(monkeypatch):
    async def run():
        with create_pipe_input() as pipe:
            prompt = PromptSession(input=pipe, output=DummyOutput())
            terminal = PromptTerminal(prompt)
            reading = asyncio.create_task(terminal.read("test> "))
            await asyncio.sleep(0.05)
            pipe.send_text("click 12")
            await asyncio.sleep(0.05)
            assert prompt.default_buffer.text == "click 12"
            await terminal.write("State: changed 中文\x1b[2J")
            assert prompt.default_buffer.text == "click 12"
            pipe.send_text("3\n")
            assert await asyncio.wait_for(reading, 2) == "click 123"

    asyncio.run(run())


def test_safe_terminal_control_characters():
    assert "\x1b" not in safe_text("中文\x1b[2J\r\n")
    assert "\\u001b" in safe_text("\x1b")
    assert len(safe_text("x" * 10000)) < 4200


class TestTerminal:
    __test__ = False

    def __init__(self):
        self.queue = asyncio.Queue()
        self.output = []

    async def read(self, prompt):
        value = await self.queue.get()
        if isinstance(value, BaseException):
            raise value
        return value

    async def write(self, text):
        self.output.append(text)


class Coordinator:
    latest = None

    def __init__(self):
        self.calls = []
        self.entered = asyncio.Event()
        self.drained = False

    async def execute_text(self, text):
        self.calls.append(text)
        self.entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.02)
            self.drained = True

    def take_change(self):
        return None

    async def stop(self):
        self.calls.append("stop")

    async def start(self):
        self.calls.append("resume")


def test_busy_rejection_and_eof_drains():
    async def run():
        coordinator, terminal = Coordinator(), TestTerminal()
        task = asyncio.create_task(interact(coordinator, terminal, lambda: True))
        await terminal.queue.put("click 123")
        await coordinator.entered.wait()
        await terminal.queue.put("click 123")
        await terminal.queue.put("?")
        await asyncio.sleep(0.02)
        await terminal.queue.put(EOFError())
        await task
        assert coordinator.calls == ["click 123"]
        assert coordinator.drained
        assert sum("Busy:" in s for s in terminal.output) == 2

    asyncio.run(run())


def test_help_long_input_stop_resume_and_ctrl_c():
    async def run():
        coordinator, terminal = Coordinator(), TestTerminal()
        task = asyncio.create_task(interact(coordinator, terminal, lambda: False))
        for value in ("help", "x" * 1025, "stop", "resume", KeyboardInterrupt()):
            await terminal.queue.put(value)
            await asyncio.sleep(0.02)
        await task
        assert coordinator.calls == ["stop", "resume"]
        assert any("exceeds 1024" in s for s in terminal.output)
        assert any("no reconnect/replay" in s for s in terminal.output)

    asyncio.run(run())


def test_unknown_reports_without_retry():
    class Unknown(Coordinator):
        async def execute_text(self, text):
            self.calls.append(text)
            state = SimpleNamespace(
                status="ERROR", interaction_revision=None, diagnostic="input_unknown"
            )
            obs = SimpleNamespace(state=state, source=None, expired=True)
            return SimpleNamespace(outcome="unknown", observation=obs)

    async def run():
        coordinator, terminal = Unknown(), TestTerminal()
        task = asyncio.create_task(interact(coordinator, terminal, lambda: False))
        await terminal.queue.put("click 123")
        await asyncio.sleep(0.05)
        await terminal.queue.put("quit")
        await task
        assert coordinator.calls == ["click 123"]
        assert any("Input unknown" in s for s in terminal.output)

    asyncio.run(run())
