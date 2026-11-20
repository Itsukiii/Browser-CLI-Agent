"""Real-browser test ownership and safe diagnostics, never a CDP simulator."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import asdict

from bca.core.browser import BrowserCaptureProvider, BrowserSession
from bca.core.plugins import PluginLifecycleState
from bca.core.runtime import BrowserFreshness, EventBus, SchedulerState, StateStore
from examples.plugin_integration import Composition, close_targets, navigate


@asynccontextmanager
async def harness(tmp_path, *, proxy=None, observation_timeout=10):
    tasks = asyncio.all_tasks()
    owner = BrowserSession(os.environ["BCA_CDP_ENDPOINT"])
    await owner.connect()
    original = {t.target_id for t in await owner.list_targets()}
    owned = set()
    session = BrowserSession(proxy.url if proxy else os.environ["BCA_CDP_ENDPOINT"])
    states, events = StateStore(), EventBus()
    raw = BrowserCaptureProvider(session, timeout=0.3 if proxy else 10)
    inputs = part = None
    report = {"evidence": "real-browser", "status": "running"}
    try:
        target = (await owner.connection.send("Target.createTarget", {"url": "about:blank"}))[
            "targetId"
        ]
        owned.add(target)
        await session.connect()
        await session.bind(target)
        await navigate(session)
        await raw.start()
        policy = BrowserFreshness(session, states)
        inputs = policy.create_input_provider(timeout=0.3 if proxy else 10)
        await inputs.start()
        part = Composition(
            session, raw, inputs, states, events, policy, observation_timeout=observation_timeout
        )
        value = dict(
            owner=owner,
            session=session,
            states=states,
            events=events,
            raw=raw,
            inputs=inputs,
            part=part,
            policy=policy,
            owned=owned,
            target=target,
            report=report,
        )
        yield value
        report["status"] = "passed"
    except BaseException as exc:
        report.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        errors = []
        if part:
            try:
                await part.close()
            except BaseException as exc:
                errors.append(type(exc).__name__)
            report["plugin"] = asdict(part.manager.snapshot())
            report["runtime"] = asdict(part.controller.snapshot())
            assert part.manager.snapshot().state is PluginLifecycleState.CLOSED
            assert part.controller.state is SchedulerState.STOPPED
            assert part.controller.snapshot().actions.pending == 0
        if inputs:
            report["uncertain"] = inputs.input_state_uncertain
            if inputs.last_error:
                report["input_error"] = inputs.last_error.details
            await inputs.close()
        await raw.close()
        await session.close()
        await states.close()
        await events.close()
        await close_targets(owner, owned, original)
        await owner.close()
        # The proxy's own relay tasks are checked after its context has exited.
        remaining = asyncio.all_tasks() - tasks
        report["cleanup"] = dict(
            errors=errors,
            pending=session.connection.pending_count,
            reader=session.connection.reader_running,
            connected=session.connected,
            owned_targets_remaining=0,
            original_targets_preserved=True,
            plugin_runtime_tasks=[
                t.get_name() for t in remaining if t.get_name().startswith("bca.")
            ],
        )
        assert not session.connection.pending_count and not session.connection.reader_running
        assert not report["cleanup"]["plugin_runtime_tasks"]
        (tmp_path / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


async def started(h):
    await h["part"].start()
    async with asyncio.timeout(10):
        await h["states"].wait_for_update(0)
    await h["part"].controller.pause()
    assert h["states"].version == 1


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.001)


def run(coro):
    async def bounded():
        before = asyncio.all_tasks()
        async with asyncio.timeout(30):
            await coro
        assert not asyncio.all_tasks() - before

    asyncio.run(bounded())
