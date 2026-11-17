import asyncio
import gc
import weakref

import pytest

from bca.core.errors import LifecycleError
from bca.core.protocol import PageState
from bca.core.runtime import ActionBatch, RuntimeController, StateStore

from ..browser.test_input import InputPeer
from .action_fakes import Context, Input, bounded, observe
from .test_browser_freshness import setup


@pytest.mark.parametrize("retained", ["frame", "retired_provider"])
def test_policy_does_not_own_unneeded_resource_objects(retained):
    async def run():
        async with InputPeer() as peer:
            session, capture, states, policy, pipeline = await setup(peer)
            try:
                if retained == "frame":
                    token = await policy.begin()
                    frame = await policy.capture(capture)
                    ref = weakref.ref(frame)
                    state = PageState(
                        plugin_id="fixture", sequence=2, source_frame_id=frame.frame_id
                    )
                    assert await policy.validate(token, state)
                    await states.publish(state)
                    policy.commit(token, states.snapshot())
                    del frame
                else:
                    provider = policy.create_input_provider()
                    await provider.start()
                    ref = weakref.ref(provider)
                    await provider.close()
                    del provider
                gc.collect()
                assert ref() is None
            finally:
                await capture.close()
                await session.close()

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("operation", ["submit", "recover", "pause", "resume"])
def test_observation_callback_cannot_wait_on_its_own_gate(operation):
    async def run():
        states, context, provider = StateStore(), Context(), Input()
        entered = asyncio.Event()

        async def callback():
            with pytest.raises(LifecycleError):
                if operation == "submit":
                    await controller.submit(ActionBatch(actions=()))
                elif operation == "recover":
                    await controller.recover(Input(), context.reference())
                else:
                    await getattr(controller, operation)()
            entered.set()
            return await observe()

        controller = RuntimeController(callback, provider, states, context)
        await controller.start()
        try:
            async with asyncio.timeout(1):
                await entered.wait()
        finally:
            await controller.stop()

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("operation", ["pause", "resume"])
def test_input_callback_cannot_await_controller_lifecycle(operation):
    async def run():
        states, context = StateStore(), Context()

        class CallbackInput(Input):
            async def execute(self, action):
                with pytest.raises(LifecycleError):
                    await getattr(controller, operation)()
                return await super().execute(action)

        provider = CallbackInput()
        controller = RuntimeController(observe, provider, states, context)
        await controller.start()
        await states.wait_for_update(0)
        await controller.pause()
        from .action_fakes import batch

        await controller.submit(batch(context))
        await controller.stop()

    asyncio.run(bounded(run()))
