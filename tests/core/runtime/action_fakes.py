import asyncio
from datetime import UTC, datetime

from bca.core.protocol import Action, ActionResult, ActionStatus, ActionType, ErrorDetail, PageState
from bca.core.providers import InputProvider
from bca.core.runtime import ActionBatch, ActionObservationRef


async def bounded(coro):
    async with asyncio.timeout(5):
        return await coro


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0)


def action(page="page", **kwargs):
    return Action(page_id=page, type=ActionType.TEXT_INPUT, text="private payload", **kwargs)


def batch(context, count=1):
    return ActionBatch(
        actions=tuple(action() for _ in range(count)), observation=context.reference()
    )


class Context:
    def __init__(self, states=None):
        self.states = states
        self.ref = ActionObservationRef(version=1, token=object())
        self.valid = True
        self.entered = asyncio.Event()
        self.gate = asyncio.Event()
        self.gate.set()
        self.can_recover = False

    async def begin(self):
        return object()

    async def validate(self, token, state):
        return self.valid

    def commit(self, token, snapshot):
        self.ref = ActionObservationRef(version=snapshot.version, token=token)

    def reference(self):
        return self.ref

    async def check(self, reference, action):
        self.entered.set()
        await self.gate.wait()
        return self.valid and reference is self.ref

    async def allow_recovery(self, previous, replacement, reference, blocked_reference):
        await self.gate.wait()
        return self.can_recover and reference is self.ref


class Input(InputProvider):
    def __init__(self):
        self.ready = True
        self.closed = False
        self.input_state_uncertain = False
        self.calls = []
        self.entered = asyncio.Event()
        self.gate = asyncio.Event()
        self.gate.set()
        self.cleanup = asyncio.Event()
        self.cleanup.set()
        self.cleaning = asyncio.Event()
        self.cleaned = False
        self.failure_at = None
        self.error = None
        self.wrong_id = False
        self.after = None

    @property
    def available(self):
        return self.ready

    async def start(self):
        self.ready = True

    async def close(self):
        self.closed = True
        self.ready = False

    async def execute(self, a):
        self.calls.append(a)
        self.entered.set()
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            self.cleaning.set()
            await self.cleanup.wait()
            self.cleaned = True
            raise
        if self.error:
            raise self.error
        if self.after:
            self.after()
        failed = self.failure_at == len(self.calls)
        return ActionResult(
            action_id="wrong" if self.wrong_id else a.action_id,
            status=ActionStatus.FAILED if failed else ActionStatus.SUCCEEDED,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            error=ErrorDetail(code="fake", message="private") if failed else None,
        )


async def observe():
    return PageState(plugin_id="fake", sequence=0)
