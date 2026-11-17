import asyncio

import pytest

from bca.core.browser import BrowserCaptureProvider, BrowserSession
from bca.core.errors import LifecycleError
from bca.core.protocol import PageState
from bca.core.runtime import (
    ActionObservationRef,
    BrowserFreshness,
    ObservationPipeline,
    StateStore,
)

from ..browser.test_input import InputPeer, action
from .action_fakes import bounded


async def setup(peer):
    session = BrowserSession(peer.endpoint)
    await session.connect()
    await session.bind("page-a")
    capture = BrowserCaptureProvider(session)
    await capture.start()
    states = StateStore()
    policy = BrowserFreshness(session, states)

    async def observe():
        frame = await policy.capture(capture)
        return PageState(plugin_id="fake", sequence=0, source_frame_id=frame.frame_id)

    pipeline = ObservationPipeline(observe, states, freshness=policy, on_commit=policy.commit)
    await pipeline.run_once()
    return session, capture, states, policy, pipeline


@pytest.mark.parametrize(
    "change",
    ["url", "document", "scroll", "size", "dpr", "zoom", "rebind", "version", "forged", "page"],
)
def test_committed_reference_and_detected_changes(change):
    async def run():
        async with InputPeer() as peer:
            session, capture, states, policy, pipeline = await setup(peer)
            ref = policy.reference()
            assert ref and await policy.check(ref, action())
            if change == "url":
                peer.runtime["href"] = "https://example.invalid/"
            elif change == "document":
                peer.runtime["timeOrigin"] += 1
            elif change == "scroll":
                peer.runtime["x"] += 1
                peer.visual["pageX"] += 1
            elif change == "size":
                peer.visual["clientWidth"] += 1
            elif change == "dpr":
                peer.runtime["dpr"] += 1
            elif change == "zoom":
                peer.visual["zoom"] += 0.1
            elif change == "rebind":
                await session.unbind()
                await session.bind("page-a")
            elif change == "version":
                await states.publish(PageState(plugin_id="external", sequence=1))
            elif change == "forged":
                ref = ActionObservationRef(version=ref.version, token=ref.token)
            a = action(page_id="wrong") if change == "page" else action()
            assert not await policy.check(ref, a)
            await capture.close()
            await session.close()

    asyncio.run(bounded(run()))


@pytest.mark.parametrize("mode", ["untracked", "wrong_source", "changed", "unpublished"])
def test_only_verified_published_actual_frames_authorize(mode):
    async def run():
        async with InputPeer() as peer:
            session, capture, states, policy, pipeline = await setup(peer)
            old_ref = policy.reference()
            token = await policy.begin()
            frame = await (
                capture.capture("page-a") if mode == "untracked" else policy.capture(capture)
            )
            state = PageState(
                plugin_id="fake",
                sequence=1,
                source_frame_id="wrong" if mode == "wrong_source" else frame.frame_id,
            )
            if mode == "changed":
                peer.runtime["timeOrigin"] += 1
            valid = await policy.validate(token, state)
            assert valid == (mode == "unpublished")
            assert policy.reference() is old_ref
            assert states.version == 1
            if mode != "unpublished":
                with pytest.raises(LifecycleError):
                    policy.commit(token, states.snapshot())
            await capture.close()
            await session.close()

    asyncio.run(bounded(run()))


def test_recovery_cannot_be_provider_recreation():
    async def run():
        async with InputPeer() as peer:
            session, capture, states, policy, pipeline = await setup(peer)
            original = policy.create_input_provider()
            replacement = policy.create_input_provider()
            await original.start()
            await replacement.start()
            ref = policy.reference()
            await pipeline.run_once()
            assert not await policy.allow_recovery(original, replacement, policy.reference(), ref)
            await original.close()
            await replacement.close()
            await capture.close()
            await session.close()

    asyncio.run(bounded(run()))
