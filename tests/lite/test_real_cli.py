"""Windows ConPTY drives installed CLI; real Edge/Maa, DOM is oracle/stimulus only."""

# ruff: noqa: E402
import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("maa")
winpty = pytest.importorskip("winpty")
from bca.core.browser import BrowserSession
from examples.browser_end_to_end import evaluate

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(
        not os.environ.get("BCA_CDP_ENDPOINT"), reason="explicit isolated Edge required"
    ),
]
ROOT = Path(__file__).resolve().parents[2]


class Console:
    def __init__(self, args, output):
        self.output = output
        self.text = ""
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        self.process = winpty.PtyProcess.spawn(
            args,
            cwd=os.environ.get("BCA_CLI_CWD", str(ROOT)),
            env=env,
            dimensions=(35, 160),
            backend=1,
        )
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        with self.output.open("w", encoding="utf-8") as stream:
            while True:
                try:
                    value = self.process.read(4096)
                except (EOFError, OSError):
                    return
                if not value:
                    return
                self.text += value
                stream.write(value)
                stream.flush()

    def plain(self):
        return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", self.text).replace("\r", "")

    async def expect(self, text, after=0):
        async with asyncio.timeout(30):
            while text not in self.plain()[after:]:
                if not self.process.isalive():
                    raise AssertionError(f"CLI exited before {text}: {self.plain()[-1500:]}")
                await asyncio.sleep(0.05)

    def send(self, text):
        self.process.write(text)


def command():
    executable = os.environ.get("BCA_CLI_PYTHON", sys.executable)
    return [
        executable,
        "-m",
        "bca.lite",
        "--config",
        str(ROOT / "configs/lite.example.toml"),
        "--endpoint",
        os.environ["BCA_CDP_ENDPOINT"],
        "--create-fixture",
    ]


@pytest.mark.parametrize("ending", ["quit", "ctrl_c", "eof", "target_lost"])
def test_real_editable_cli(tmp_path, ending):
    out = Path(os.environ.get("BCA_CLI_EVIDENCE", str(tmp_path))) / ending
    out.mkdir(parents=True, exist_ok=False)

    async def run():
        session = BrowserSession(os.environ["BCA_CDP_ENDPOINT"])
        await session.connect()
        original = {t.target_id for t in await session.list_targets()}
        console = None
        report = {"command": command(), "ending": ending, "start": time.time(), "stimuli": []}
        try:
            console = Console(command(), out / "transcript.txt")
            await console.expect("Bound Target")
            async with asyncio.timeout(10):
                while True:
                    created = [
                        t.target_id
                        for t in await session.list_targets()
                        if t.target_id not in original
                    ]
                    if len(created) == 1:
                        break
                    await asyncio.sleep(0.05)
            target = created[0]
            report["target"] = target
            await session.bind(target)
            await console.expect("revision=123")
            console.send("?")
            console.send("\r")
            await console.expect("Result: read")
            # Keep half a command in the real console while a changed state renders.
            console.send("click 45")
            await asyncio.sleep(0.3)
            await evaluate(session, "configure('456',1)")
            await console.expect("revision=456")
            console.send("6\r")
            await console.expect("Result: confirmed")
            await console.expect("revision=457")
            report["dom"] = await evaluate(session, "hits")
            assert len(report["dom"]) == 1 and report["dom"][0]["id"] == "button"
            assert report["dom"][0]["round"] == "456"
            if ending == "quit":
                for text, expect in [
                    ("click 456", "Rejected:"),
                    ("stop", "Stopped;"),
                    ("stop", "Stopped;"),
                    ("resume", "Observation resumed."),
                ]:
                    offset = len(console.plain())
                    console.send(text + "\r")
                    await console.expect(expect, offset)
                for count, expected in [(0, "NOT_FOUND"), (2, "AMBIGUOUS"), (1, "MATCHED")]:
                    offset = len(console.plain())
                    await evaluate(session, f"configure('457',{count})")
                    await console.expect(expected, offset)
                # Long/invalid/Unicode/batched input: no extra confirmed action.
                console.send("中文非法命令\r" + "x" * 1030 + "\r")
                await console.expect("exceeds 1024")
                console.send("?\r?\r?\r")
                await console.expect("Busy:")
                await asyncio.sleep(1)
                assert await evaluate(session, "hits.length") == 1
                console.send("quit\r")
            elif ending == "ctrl_c":
                console.send("?\r")
                await asyncio.sleep(0.02)
                console.send("\x03")
            elif ending == "eof":
                console.send("\x04")
            else:
                await session.connection.send("Target.closeTarget", {"targetId": target})
                await console.expect("no reconnect/replay")
                console.send("click 457\r")
                await console.expect("Rejected:")
                console.send("quit\r")
            async with asyncio.timeout(30):
                while console.process.isalive():
                    await asyncio.sleep(0.05)
            console.thread.join(timeout=2)
            report["exit_code"] = console.process.exitstatus
            report["transcript"] = console.plain()
            assert "released=True" in report["transcript"]
            assert "pending=0 reader=False" in report["transcript"]
            async with asyncio.timeout(5):
                while target in {t.target_id for t in await session.list_targets()}:
                    await asyncio.sleep(0.05)
            remaining = {t.target_id for t in await session.list_targets()}
            report["original_preserved"] = original.issubset(remaining)
            assert report["original_preserved"]
            assert report["exit_code"] == 0
        finally:
            if console is not None and console.process.isalive():
                console.send("\x03")
                await asyncio.sleep(2)
                if console.process.isalive():
                    console.process.terminate(force=True)  # Only this test-owned child on failure.
                    report["forced_test_cleanup"] = True
            await session.close()
            report["end"] = time.time()
            (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    asyncio.run(run())


def test_non_tty_refused(tmp_path):
    result = subprocess.run(command(), capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert "requires a terminal" in result.stderr


@pytest.mark.parametrize("fault", ["stop_failed", "pre_click_failed"])
def test_cli_fault_diagnostics(tmp_path, fault):
    out = Path(os.environ.get("BCA_CLI_EVIDENCE", str(tmp_path))) / fault
    out.mkdir(parents=True, exist_ok=False)

    async def run():
        session = BrowserSession(os.environ["BCA_CDP_ENDPOINT"])
        await session.connect()
        original = {t.target_id for t in await session.list_targets()}
        args = command()
        args[1:3] = ["-m", "tests.lite.cli_fault_child", fault]
        console = Console(args, out / "transcript.txt")
        report = {"fault": fault, "command": args}
        target = None
        try:
            await console.expect("revision=123")
            created = [
                t.target_id for t in await session.list_targets() if t.target_id not in original
            ]
            assert len(created) == 1
            target = created[0]
            await session.bind(target)
            if fault == "pre_click_failed":
                console.send("click 123\r")
                await console.expect("Input unknown")
                console.send("click 123\r")
                await console.expect("Rejected:")
                report["dom"] = await evaluate(session, "hits")
                assert report["dom"] == []
            console.send("quit\r")
            async with asyncio.timeout(15):
                while console.process.isalive():
                    await asyncio.sleep(0.05)
            console.thread.join(timeout=2)
            report["exit_code"] = console.process.exitstatus
            report["transcript"] = console.plain()
            if fault == "stop_failed":
                assert report["exit_code"] == 3
                assert "released=False" in console.plain()
                assert "CDP closed:" not in console.plain()
                assert target in {t.target_id for t in await session.list_targets()}
                report["dependencies_not_closed_by_cli"] = True
            else:
                assert report["exit_code"] == 0
                assert "released=True" in console.plain()
        finally:
            if console.process.isalive():
                console.process.terminate(force=True)
                report["forced_test_cleanup"] = True
            if target and target in {t.target_id for t in await session.list_targets()}:
                await session.connection.send("Target.closeTarget", {"targetId": target})
                report["test_harness_closed_owned_target"] = True
            assert original.issubset({t.target_id for t in await session.list_targets()})
            await session.close()
            (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    asyncio.run(run())


@pytest.mark.skipif(not os.environ.get("BCA_CLI_LONG"), reason="explicit 65 second CLI run")
def test_cli_observation_cost(tmp_path):
    out = Path(os.environ.get("BCA_CLI_EVIDENCE", str(tmp_path))) / "performance"
    out.mkdir(parents=True, exist_ok=False)
    os.environ["BCA_CLI_METRICS"] = str((out / "metrics.json").resolve())

    async def run():
        args = command()
        args[1:3] = ["-m", "tests.lite.cli_metrics_child"]
        console = Console(args, out / "transcript.txt")
        try:
            await console.expect("revision=123")
            # No extra refresh calls: measure actual Coordinator periodic work.
            await asyncio.sleep(65)
            console.send("quit\r")
            async with asyncio.timeout(15):
                while console.process.isalive():
                    await asyncio.sleep(0.05)
            console.thread.join(timeout=2)
            assert console.process.exitstatus == 0
            data = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
            assert data["stats"]["valid"] / data["duration"] >= 1
            assert console.plain().count("State: MATCHED") == 1
            assert data["close"]["released"]
        finally:
            if console.process.isalive():
                console.send("\x03")
                await asyncio.sleep(2)
                if console.process.isalive():
                    console.process.terminate(force=True)

    try:
        asyncio.run(run())
    finally:
        del os.environ["BCA_CLI_METRICS"]


def test_interactive_explicit_selection_preserves_existing_target(tmp_path):
    from bca.lite.fixture import fixture_bundle
    from tests.lite.test_real_vision import create

    out = Path(os.environ.get("BCA_CLI_EVIDENCE", str(tmp_path))) / "selection"
    out.mkdir(parents=True, exist_ok=False)

    async def run():
        session = BrowserSession(os.environ["BCA_CDP_ENDPOINT"])
        await session.connect()
        console = target = None
        report = {}
        try:
            with fixture_bundle() as bundle:
                target = await create(session, bundle)
            await session.send(
                "Emulation.setDeviceMetricsOverride",
                {"width": 640, "height": 400, "deviceScaleFactor": 1, "mobile": False},
            )
            args = command()[:-1]  # No --create-fixture; must explicitly choose, never default.
            console = Console(args, out / "transcript.txt")
            await console.expect("Exact Target ID")
            console.send(target + "\r")
            await console.expect("revision=123")
            console.send("?\r")
            await console.expect("Result: read")
            console.send("quit\r")
            async with asyncio.timeout(15):
                while console.process.isalive():
                    await asyncio.sleep(0.05)
            console.thread.join(timeout=2)
            assert console.process.exitstatus == 0
            assert target in {t.target_id for t in await session.list_targets()}
            report = {
                "target_preserved": True,
                "exit_code": console.process.exitstatus,
                "transcript": console.plain(),
                "command": args,
            }
        finally:
            if console and console.process.isalive():
                console.process.terminate(force=True)
                report["forced_test_cleanup"] = True
            if target:
                await session.connection.send("Target.closeTarget", {"targetId": target})
            await session.close()
            (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    asyncio.run(run())


def test_expired_cli_refuses_action(tmp_path):
    out = Path(os.environ.get("BCA_CLI_EVIDENCE", str(tmp_path))) / "expired"
    out.mkdir(parents=True, exist_ok=False)

    async def run():
        session = BrowserSession(os.environ["BCA_CDP_ENDPOINT"])
        await session.connect()
        original = {t.target_id for t in await session.list_targets()}
        args = [*command(), "--max-frame-age", "0.000001"]
        console = Console(args, out / "transcript.txt")
        report = {"command": args}
        try:
            await console.expect("expired=True")
            created = [
                t.target_id for t in await session.list_targets() if t.target_id not in original
            ]
            assert len(created) == 1
            await session.bind(created[0])
            console.send("click 123\r")
            await console.expect("Rejected:")
            report["dom"] = await evaluate(session, "hits")
            assert report["dom"] == []
            console.send("quit\r")
            async with asyncio.timeout(15):
                while console.process.isalive():
                    await asyncio.sleep(0.05)
            console.thread.join(timeout=2)
            assert console.process.exitstatus == 0
            report["exit_code"] = console.process.exitstatus
            report["transcript"] = console.plain()
            assert "released=True" in console.plain()
        finally:
            if console.process.isalive():
                console.process.terminate(force=True)
                report["forced_test_cleanup"] = True
            await session.close()
            (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    asyncio.run(run())
