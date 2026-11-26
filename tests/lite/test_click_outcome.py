"""Per-action native/CDP agreement. Actual Maa jobs plus explicit failure injection."""

# ruff: noqa: E402
import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("maa")
from bca.lite.bridge import BridgeError
from bca.lite.vision_types import TemplateRequest, VisionError
from tests.lite.test_observation import setup
from tests.lite.test_vision_native import model_spec, record


@pytest.mark.parametrize(
    "fault",
    [
        "pre_failed",
        "pre_exception",
        "false_success",
        "callback_false",
        "ack_lost",
        "post_failed",
        "post_exception",
    ],
)
def test_previous_confirmation_cannot_confirm_next_job(tmp_path, monkeypatch, fault):
    async def run():
        c, f, p, b, capture, _, inputs = setup(tmp_path, monkeypatch)
        await f.start()
        callbacks = []
        original_click = b.click

        def traced(x, y):
            callbacks.append((x, y))
            return original_click(x, y)

        monkeypatch.setattr(b, "click", traced)
        try:
            first = await f.recognize((TemplateRequest("button", "marker.png"),))
            assert await f.click(first, "button", 0) == "confirmed"
            second = await f.recognize((TemplateRequest("button", "marker.png"),))
            assert first.capture.source_ref is not second.capture.source_ref
            assert b.input_outcome == "confirmed"  # Capture alone is not a new action.
            controller = f._native.controller
            post = controller.post_click
            if fault in ("pre_failed", "false_success"):
                job = SimpleNamespace(succeeded=fault == "false_success")
                job.wait = lambda: job
                monkeypatch.setattr(controller, "post_click", lambda *args: job)
            elif fault == "pre_exception":

                def fail(*args):
                    raise RuntimeError("native submission failed before callback")

                monkeypatch.setattr(controller, "post_click", fail)
            elif fault == "callback_false":

                def rejected(x, y):
                    callbacks.append((x, y))
                    return False

                monkeypatch.setattr(b, "click", rejected)
            elif fault == "ack_lost":

                async def ack_lost(action):
                    inputs.actions.append(action)
                    raise RuntimeError("ACK lost after input dispatch")

                monkeypatch.setattr(inputs, "execute", ack_lost)
            else:

                def post_with_failure(*args):
                    real = post(*args)

                    def wait():
                        real.wait()
                        assert real.succeeded
                        if fault == "post_exception":
                            raise RuntimeError("failure after confirmed native callback")
                        return SimpleNamespace(succeeded=False)

                    return SimpleNamespace(wait=wait)

                monkeypatch.setattr(controller, "post_click", post_with_failure)
            outcome = await f.click(second, "button", 0)
            assert outcome == "unknown" and not f.connected
            diagnostic = b.last_error
            before = (len(callbacks), len(inputs.actions))
            with pytest.raises(VisionError):
                await f.click(second, "button", 0)
            with pytest.raises(BridgeError):
                await b.authorize(second.capture.source_ref)
            assert not await asyncio.to_thread(b.click, 77, 63)
            # Raw rejected callback is counted, but it must not send input.
            assert len(inputs.actions) == before[1]
            expected_callbacks = 1 if fault.startswith("pre_") or fault == "false_success" else 2
            expected_inputs = 2 if fault in ("ack_lost", "post_failed", "post_exception") else 1
            assert before == (expected_callbacks, expected_inputs)
            record(
                tmp_path,
                f"click-{fault}",
                {
                    "first": "confirmed",
                    "second": outcome,
                    "callbacks_before_retry": before[0],
                    "inputs_total": len(inputs.actions),
                    "second_frame": second.capture.source_ref.frame.frame_id,
                    "first_frame": first.capture.source_ref.frame.frame_id,
                    "diagnostic": diagnostic,
                    "retired": not f.connected,
                },
            )
        finally:
            assert (await c.aclose()).released

    asyncio.run(run())


def test_coordinator_does_not_report_previous_confirmed(tmp_path, monkeypatch):
    model = model_spec()

    async def run():
        c, f, p, b, capture, _, inputs = setup(tmp_path, monkeypatch, model=model)
        await c.start()
        try:
            assert (await c.execute_text("click 123")).outcome == "confirmed"
            callbacks = []
            click = b.click

            def traced(x, y):
                callbacks.append((x, y))
                return click(x, y)

            monkeypatch.setattr(b, "click", traced)
            job = SimpleNamespace(succeeded=False)
            job.wait = lambda: job
            monkeypatch.setattr(f._native.controller, "post_click", lambda *args: job)
            result = await c.execute_text("click 123")
            assert result.outcome == "unknown" and result.observation.source is None
            assert not callbacks and len(inputs.actions) == 1
            with pytest.raises(VisionError):
                await c.execute_text("click 123")
            record(
                tmp_path,
                "coordinator-native-pre-failure",
                {
                    "outcome": result.outcome,
                    "second_callbacks": len(callbacks),
                    "inputs": len(inputs.actions),
                    "captures": capture.count,
                },
            )
        finally:
            assert (await c.aclose()).released

    asyncio.run(run())


def test_successful_new_action_and_consumed_authorization(tmp_path, monkeypatch):
    async def run():
        c, f, p, b, capture, _, inputs = setup(tmp_path, monkeypatch)
        await f.start()
        try:
            for _ in range(2):
                batch = await f.recognize((TemplateRequest("button", "marker.png"),))
                await b.authorize(batch.capture.source_ref)
                await b.authorize(batch.capture.source_ref)
                assert await f.click(batch, "button", 0) == "confirmed"
                with pytest.raises(BridgeError):
                    await b.authorize(batch.capture.source_ref)
                with pytest.raises(VisionError):
                    await f.click(batch, "button", 0)
            assert len(inputs.actions) == 2
            record(tmp_path, "confirmed-new-actions", {"inputs": 2, "captures": capture.count})
        finally:
            assert (await c.aclose()).released

    asyncio.run(run())
