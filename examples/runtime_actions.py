"""No-browser example of trusted simulated observations and FIFO action submission."""

import asyncio
from datetime import UTC, datetime

from bca.core.protocol import Action, ActionResult, ActionStatus, ActionType, PageState
from bca.core.providers import InputProvider
from bca.core.runtime import (
    ActionBatch,
    ActionObservationRef,
    RuntimeController,
    StateSnapshot,
    StateStore,
)


class SimulatedInput(InputProvider):
    @property
    def available(self) -> bool:
        return True

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def execute(self, action: Action) -> ActionResult:
        return ActionResult(
            action_id=action.action_id,
            status=ActionStatus.SUCCEEDED,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )


class SimulatedContext:
    """Simulation only. Use BrowserFreshness for actual Browser input."""

    def __init__(self, states: StateStore) -> None:
        self.states = states
        self.ref: ActionObservationRef | None = None

    async def begin(self) -> object:
        return object()

    async def validate(self, token: object, state: PageState) -> bool:
        return True

    def commit(self, token: object, snapshot: StateSnapshot) -> None:
        self.ref = ActionObservationRef(version=snapshot.version, token=token)

    def reference(self) -> ActionObservationRef | None:
        return self.ref

    async def check(self, reference: ActionObservationRef | None, action: Action) -> bool:
        return (
            reference is not None
            and reference is self.ref
            and reference.version == self.states.version
            and action.page_id == "simulated"
        )

    async def allow_recovery(
        self,
        previous: InputProvider,
        replacement: InputProvider,
        reference: ActionObservationRef,
        blocked_reference: ActionObservationRef | None,
    ) -> bool:
        return False  # Simulation deliberately supplies no Browser recovery evidence.


async def main() -> None:
    states, provider = StateStore(), SimulatedInput()
    context = SimulatedContext(states)

    async def observe() -> PageState:
        return PageState(plugin_id="simulation", sequence=states.version)

    controller = RuntimeController(observe, provider, states, context, interval=100)
    try:
        await controller.start()
        await states.wait_for_update(0)
        await controller.pause()
        batch = ActionBatch(
            actions=(Action(page_id="simulated", type=ActionType.TEXT_INPUT, text="demo"),),
            observation=controller.reference(),
        )
        result = await controller.submit(batch)
        await controller.resume()
        await states.wait_for_update(1)
        await controller.pause()
        stale = await controller.submit(batch)
        print(
            {
                "first": result.status.value,
                "old_reference": stale.status.value,
                "state_version": states.version,
                "accepted": controller.snapshot().actions.accepted,
            }
        )
    finally:
        await controller.stop()
        await provider.close()
        await states.close()


if __name__ == "__main__":
    asyncio.run(main())
