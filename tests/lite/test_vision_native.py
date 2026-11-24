"""Real Maa DLL + deterministic image provider. Not Edge/02.3 acceptance."""
# ruff: noqa: E402

import asyncio
import dataclasses
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("maa")
from bca.lite._native_vision import normalize
from bca.lite.bridge import BridgeError
from bca.lite.vision import MaaVisionFacade
from bca.lite.vision_resources import OCRModelSpec, ResourceSpec
from bca.lite.vision_types import OCRRequest, RecognitionStatus, TemplateRequest, VisionError
from tests.lite.vision_fixture import bridge_for, bundle_at, scene

MANIFEST = Path(__file__).resolve().parents[2] / "docs/lite/models/ppocr-v3-en.json"


def model_spec():
    value = os.environ.get("BCA_OCR_MODEL")
    if not value:
        pytest.skip("set BCA_OCR_MODEL to an explicitly provisioned ppocr-v3-en directory")
    return OCRModelSpec(Path(value).resolve(), MANIFEST)


def record(tmp_path, name, payload, image=None):
    root = Path(os.environ.get("BCA_VISION_EVIDENCE", str(tmp_path)))
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if image is not None:
        image.save(root / f"{name}.png")


def result_record(batch):
    return {
        "frame_id": batch.capture.source_ref.frame.frame_id,
        "binding": batch.capture.binding,
        "size": [batch.capture.width, batch.capture.height],
        "source_current": batch.source_current,
        "expired": batch.expired,
        "results": [dataclasses.asdict(r) for r in batch.results],
    }


@pytest.mark.parametrize("index", range(10))
@pytest.mark.parametrize("positive", [True, False])
def test_template_matrix(tmp_path, monkeypatch, index, positive):
    async def run():
        point = (60 + index * 4, 50 + index)
        image = scene(
            text="123" if positive else f"NO {index}", points=(point,) if positive else ()
        )
        bridge, capture, _, _ = bridge_for(monkeypatch, image)
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle_at(tmp_path / "bundle")))
        await facade.start()
        try:
            batch = await facade.recognize(
                (
                    TemplateRequest("full", "marker.png"),
                    TemplateRequest("roi", "marker.png", (40, 30, 150, 80)),
                )
            )
            assert capture.count == 1 and batch.capture.source_ref is bridge.observation
            for result in batch.results:
                assert result.status == (
                    RecognitionStatus.MATCHED if positive else RecognitionStatus.NOT_FOUND
                )
                assert result.job_status == "succeeded"  # Execution success != recognition hit.
                if positive:
                    assert result.candidates[0].box == (*point, 36, 28)
            with pytest.raises(ValueError):
                batch.capture.image.setflags(write=True)
            record(tmp_path, f"template-{positive}-{index}", result_record(batch), image)
        finally:
            report = await facade.aclose()
            assert report.released and report.destroyed == ("tasker", "controller", "resource")
            assert report.worker_thread != threading.get_ident()
            assert await facade.aclose() is report

    asyncio.run(run())


@pytest.mark.parametrize(
    "text", [str(i) for i in range(10)] + ["-1", "-20", "-305", "12", "345", "6789"]
)
def test_ocr_digits_and_roi(tmp_path, monkeypatch, text):
    model = model_spec()

    async def run():
        image = scene(text=text, points=())
        bridge, capture, _, _ = bridge_for(monkeypatch, image, max_frame_age=10)
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle_at(tmp_path / "bundle"), model))
        await facade.start()
        try:
            batch = await facade.recognize(
                (OCRRequest("full"), OCRRequest("roi", (50, 100, 350, 110)))
            )
            record(tmp_path, f"ocr-{text}", result_record(batch), image)
            assert capture.count == 1 and batch.capture.source_ref is bridge.observation
            for result in batch.results:
                assert result.status == RecognitionStatus.MATCHED
                assert [c.text for c in result.candidates] == [text]
                x, y, w, h = result.candidates[0].box
                assert x >= 50 and y >= 100 and x + w <= 400 and y + h <= 210
        finally:
            assert (await facade.aclose()).released

    asyncio.run(run())


def test_ocr_negative_and_expected_filter(tmp_path, monkeypatch):
    model = model_spec()

    async def run():
        bridge, capture, _, _ = bridge_for(monkeypatch, scene(text="", points=()))
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle_at(tmp_path / "bundle"), model))
        await facade.start()
        try:
            blank = await facade.recognize((OCRRequest("blank"),))
            capture.image = scene(text="123", points=())
            filtered = await facade.recognize((OCRRequest("filter", expected=("^999$",)),))
            for batch in (blank, filtered):
                record(tmp_path, batch.results[0].request_key, result_record(batch))
                assert batch.results[0].status == RecognitionStatus.NOT_FOUND
                assert batch.results[0].job_status == "succeeded"
            assert filtered.results[0].all_candidates[0].text == "123"
        finally:
            assert (await facade.aclose()).released

    asyncio.run(run())


def test_ambiguity_and_missing_resource(tmp_path, monkeypatch):
    async def run():
        image = scene(points=((60, 50), (150, 50)))
        bridge, _, _, _ = bridge_for(monkeypatch, image)
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle_at(tmp_path / "bundle")))
        await facade.start()
        try:
            batch = await facade.recognize(
                (
                    TemplateRequest("unique", "marker.png"),
                    TemplateRequest("many", "marker.png", unique=False),
                    TemplateRequest("missing", "missing.png"),
                    OCRRequest("ocr"),
                )
            )
            assert [r.status for r in batch.results] == [
                RecognitionStatus.AMBIGUOUS,
                RecognitionStatus.MATCHED,
                RecognitionStatus.ERROR,
                RecognitionStatus.ERROR,
            ]
            assert len(batch.results[0].candidates) == 2
            record(tmp_path, "ambiguous-missing", result_record(batch), image)
        finally:
            assert (await facade.aclose()).released

    asyncio.run(run())


@pytest.mark.parametrize(
    "entry,recognition_request",
    [("TemplateProbe", TemplateRequest("t", "marker.png")), ("OCRProbe", OCRRequest("o"))],
)
def test_pipeline_native_api_only(tmp_path, monkeypatch, entry, recognition_request):
    # Private test probe: pipeline details never become a source-authorized Batch.
    model = model_spec()

    async def run():
        bridge, capture, _, _ = bridge_for(monkeypatch, scene())
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle_at(tmp_path / "bundle"), model))
        await facade.start()
        try:

            def probe():
                job = facade._native.tasker.post_task(entry).wait()
                return normalize(job, recognition_request, 480, 240)

            result = await facade._submit(probe)
            assert result.status == RecognitionStatus.MATCHED
            assert capture.count == 1
            if entry == "TemplateProbe":
                assert result.candidates[0].box == (60, 50, 36, 28)
            else:
                assert result.candidates[0].text == "123"
            record(
                tmp_path,
                entry,
                {
                    "captures": capture.count,
                    "authorized_batch": False,
                    "result": dataclasses.asdict(result),
                },
            )
        finally:
            assert (await facade.aclose()).released

    asyncio.run(run())


@pytest.mark.parametrize("change", ["expired", "binding", "replacement"])
def test_source_rechecked_after_native_work(tmp_path, monkeypatch, change):
    async def run():
        bridge, capture, session, _ = bridge_for(monkeypatch, scene(), max_frame_age=0.2)
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle_at(tmp_path / "bundle")))
        await facade.start()
        entered, release = threading.Event(), threading.Event()
        recognize = facade._native.recognize

        def held(*args):
            entered.set()
            assert release.wait(5)
            return recognize(*args)

        monkeypatch.setattr(facade._native, "recognize", held)
        task = asyncio.create_task(facade.recognize((TemplateRequest("t", "marker.png"),)))
        try:
            while not entered.is_set():
                await asyncio.sleep(0.005)
            original = bridge.observation
            if change == "expired":
                await asyncio.sleep(0.25)
            elif change == "binding":
                session.generation += 1
            else:
                await asyncio.to_thread(
                    bridge.screencap
                )  # Deliberate external ownership violation.
            release.set()
            batch = await task
            assert batch.capture.source_ref is original
            if change == "expired":
                assert batch.expired and batch.source_current
                assert batch.results[0].status == RecognitionStatus.MATCHED
                with pytest.raises(BridgeError, match="expired"):
                    await bridge.authorize(original)
            else:
                assert (
                    not batch.source_current and batch.results[0].status == RecognitionStatus.ERROR
                )
            record(tmp_path, f"source-{change}", result_record(batch))
        finally:
            release.set()
            assert (await facade.aclose()).released

    asyncio.run(run())


def test_cancel_repeat_and_close_wait_for_native(tmp_path, monkeypatch):
    async def run():
        bridge, _, _, inputs = bridge_for(monkeypatch, scene())
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle_at(tmp_path / "bundle")))
        await facade.start()
        entered, release = threading.Event(), threading.Event()
        recognize = facade._native.recognize

        def held(*args):
            entered.set()
            assert release.wait(5)
            return recognize(*args)

        monkeypatch.setattr(facade._native, "recognize", held)
        task = asyncio.create_task(facade.recognize((TemplateRequest("t", "marker.png"),)))
        while not entered.is_set():
            await asyncio.sleep(0.005)
        task.cancel()
        await asyncio.sleep(0.01)
        task.cancel()
        close = asyncio.create_task(facade.aclose())
        await asyncio.sleep(0.01)
        close.cancel()
        await asyncio.sleep(0.01)
        assert not task.done() and not close.done()
        assert facade._native.tasker._handle
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(asyncio.CancelledError):
            await close
        report = await facade.aclose()
        assert report.released and not inputs.actions
        assert not bridge.connected
        with pytest.raises(VisionError):
            await facade.recognize((TemplateRequest("t", "marker.png"),))
        record(tmp_path, "cancel-close", dataclasses.asdict(report))

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["bundle", "model-missing", "hash"])
def test_partial_start_failure_cleanup(tmp_path, monkeypatch, fault):
    async def run():
        bundle = bundle_at(tmp_path / "bundle")
        model = None
        if fault == "bundle":
            (bundle / "pipeline/fixture.json").write_text("{invalid", encoding="utf-8")
        else:
            root = tmp_path / "model"
            root.mkdir()
            if fault == "hash":
                manifest = json.loads(MANIFEST.read_text())
                for name, info in manifest["files"].items():
                    (root / name).write_bytes(b"x" * info["size"])
            model = OCRModelSpec(root, MANIFEST)
        bridge, _, _, _ = bridge_for(monkeypatch, scene())
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle, model))
        with pytest.raises(VisionError):
            await facade.start()
        report = await facade.aclose()
        assert report.released
        if fault == "bundle":
            assert report.destroyed == ("controller", "resource")
        else:
            assert report.destroyed == ()
        record(tmp_path, f"start-{fault}", dataclasses.asdict(report))

    asyncio.run(run())


def test_repeated_native_lifecycle_and_concurrent_batches(tmp_path, monkeypatch):
    async def run():
        reports = []
        for index in range(5):
            bridge, capture, _, _ = bridge_for(monkeypatch, scene())
            facade = MaaVisionFacade(bridge, ResourceSpec(bundle_at(tmp_path / str(index))))
            await asyncio.gather(facade.start(), facade.start())
            first, second = await asyncio.gather(
                facade.recognize((TemplateRequest("t", "marker.png"),)),
                facade.recognize((TemplateRequest("t", "marker.png"),)),
            )
            assert capture.count == 2 and first.capture.source_ref is not second.capture.source_ref
            assert all(b.results[0].status == RecognitionStatus.MATCHED for b in (first, second))
            closed = await asyncio.gather(facade.aclose(), facade.aclose())
            assert closed[0] is closed[1] and closed[0].released
            reports.append(dataclasses.asdict(closed[0]))
        record(tmp_path, "lifecycle", reports)

    asyncio.run(run())


def test_malformed_details_are_error():
    job = SimpleNamespace(succeeded=False, failed=True, job_id=1, get=lambda: None)
    assert normalize(job, OCRRequest("o"), 480, 240).status == RecognitionStatus.ERROR
    reco = SimpleNamespace(
        algorithm="OCR", hit=False, reco_id=1, raw_detail={"all": [], "filtered": [], "best": None}
    )
    job.get = lambda: SimpleNamespace(nodes=[SimpleNamespace(recognition=reco)])
    assert normalize(job, OCRRequest("o"), 480, 240).status == RecognitionStatus.ERROR


def test_native_missing_model_detail_is_not_a_safe_miss(tmp_path, monkeypatch):
    from maa.pipeline import JOCR

    async def run():
        bridge, _, _, _ = bridge_for(monkeypatch, scene())
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle_at(tmp_path / "bundle")))
        await facade.start()
        try:

            def probe():
                native = facade._native
                image = native.capture()
                job = native.tasker.post_recognition("OCR", JOCR(), image).wait()
                detail = job.get()
                return {
                    "succeeded": job.succeeded,
                    "failed": job.failed,
                    "nodes": [
                        {
                            "name": n.name,
                            "hit": n.recognition.hit if n.recognition else None,
                            "raw": n.recognition.raw_detail if n.recognition else None,
                        }
                        for n in detail.nodes
                    ],
                }

            raw = await facade._submit(probe)
            guarded = await facade.recognize((OCRRequest("missing-model"),))
            assert guarded.results[0].status == RecognitionStatus.ERROR
            record(
                tmp_path, "native-missing-model", {"native": raw, "guarded": result_record(guarded)}
            )
        finally:
            assert (await facade.aclose()).released

    asyncio.run(run())


def test_invalid_template_and_too_small_roi(tmp_path, monkeypatch):
    async def run():
        bundle = bundle_at(tmp_path / "bundle")
        (bundle / "image/corrupt.png").write_bytes(b"not a png")
        bridge, _, _, _ = bridge_for(monkeypatch, scene())
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle))
        await facade.start()
        try:
            batch = await facade.recognize(
                (
                    TemplateRequest("bad", "corrupt.png"),
                    TemplateRequest("roi", "marker.png", (0, 0, 5, 5)),
                    TemplateRequest("escape", "../outside.png"),
                )
            )
            assert all(r.status == RecognitionStatus.ERROR for r in batch.results)
            record(tmp_path, "invalid-template", result_record(batch))
        finally:
            assert (await facade.aclose()).released

    asyncio.run(run())


def test_cancel_native_screenshot_drains_callback(tmp_path, monkeypatch):
    async def run():
        bridge, capture, _, inputs = bridge_for(monkeypatch, scene())
        entered, release = asyncio.Event(), asyncio.Event()
        original = capture.capture

        async def held(page):
            entered.set()
            await release.wait()
            return await original(page)

        monkeypatch.setattr(capture, "capture", held)
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle_at(tmp_path / "bundle")))
        await facade.start()
        task = asyncio.create_task(facade.recognize((TemplateRequest("t", "marker.png"),)))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        report = await facade.aclose()
        assert report.released and not inputs.actions and not bridge._tasks
        record(tmp_path, "cancel-screenshot", dataclasses.asdict(report))

    asyncio.run(run())


def test_version_guard(tmp_path, monkeypatch):
    async def run():
        bridge, _, _, _ = bridge_for(monkeypatch, scene())
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle_at(tmp_path / "bundle")))
        with monkeypatch.context() as patch:
            patch.setattr("bca.lite._native_vision.importlib.metadata.version", lambda _: "5.16.2")
            with pytest.raises(VisionError, match="v5.16.1"):
                await facade.start()
        assert facade.close_report.released

    asyncio.run(run())


def test_destroy_failure_preserves_dependencies_and_worker_for_retry(tmp_path, monkeypatch):
    from maa.library import Library

    async def run():
        bridge, _, _, _ = bridge_for(monkeypatch, scene())
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle_at(tmp_path / "bundle")))
        await facade.start()

        def fail_destroy(handle):
            raise RuntimeError("injected destroy failure before release")

        with monkeypatch.context() as patch:
            patch.setattr(Library.framework(), "MaaTaskerDestroy", fail_destroy)
            failed = await facade.aclose()
        assert not failed.released and failed.errors and not failed.destroyed
        assert facade._native.controller._handle and facade._native.resource._handle
        recovered = await facade.aclose()
        assert recovered.released and recovered.worker_thread == failed.worker_thread
        assert recovered.destroyed == ("tasker", "controller", "resource")
        record(
            tmp_path,
            "destroy-retry",
            {"failed": dataclasses.asdict(failed), "recovered": dataclasses.asdict(recovered)},
        )

    asyncio.run(run())


def test_cancel_startup_destroys_partial_owner(tmp_path, monkeypatch):
    from bca.lite._native_vision import NativeVision

    async def run():
        bridge, _, _, _ = bridge_for(monkeypatch, scene())
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle_at(tmp_path / "bundle")))
        entered, release = threading.Event(), threading.Event()
        original = NativeVision.start

        def held(owner):
            original(owner)
            entered.set()
            assert release.wait(5)

        monkeypatch.setattr(NativeVision, "start", held)
        task = asyncio.create_task(facade.start())
        while not entered.is_set():
            await asyncio.sleep(0.005)
        task.cancel()
        await asyncio.sleep(0.01)
        task.cancel()
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert facade.close_report.released
        record(tmp_path, "cancel-start", dataclasses.asdict(facade.close_report))

    asyncio.run(run())


@pytest.mark.parametrize("entry", ["TemplateProbe", "OCRProbe"])
def test_pipeline_negative_native_semantics(tmp_path, monkeypatch, entry):
    model = model_spec()

    async def run():
        bridge, capture, _, _ = bridge_for(monkeypatch, scene(text="", points=()))
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle_at(tmp_path / "bundle"), model))
        await facade.start()
        try:

            def probe():
                job = facade._native.tasker.post_task(entry).wait()
                detail = job.get()
                return {
                    "succeeded": job.succeeded,
                    "failed": job.failed,
                    "nodes": [
                        {
                            "name": n.name,
                            "hit": n.recognition.hit if n.recognition else None,
                            "raw": n.recognition.raw_detail if n.recognition else None,
                        }
                        for n in detail.nodes
                    ]
                    if detail
                    else None,
                }

            result = await facade._submit(probe)
            record(
                tmp_path,
                f"{entry}-negative",
                {"native": result, "captures": capture.count, "authorized_batch": False},
            )
            assert result["failed"] and not result["succeeded"]
            assert all(not n["hit"] for n in result["nodes"])
        finally:
            assert (await facade.aclose()).released

    asyncio.run(run())


def test_ocr_multiple_candidates_and_only_rec(tmp_path, monkeypatch):
    from PIL import ImageDraw, ImageFont

    model = model_spec()

    async def run():
        image = scene(text="123", points=())
        ImageDraw.Draw(image).text((280, 40), "456", fill="black", font=ImageFont.load_default(48))
        bridge, _, _, _ = bridge_for(monkeypatch, image, max_frame_age=10)
        facade = MaaVisionFacade(bridge, ResourceSpec(bundle_at(tmp_path / "bundle"), model))
        await facade.start()
        try:
            batch = await facade.recognize(
                (
                    OCRRequest("ambiguous"),
                    OCRRequest("many", unique=False),
                    OCRRequest("crop", (70, 125, 120, 70), only_rec=True),
                )
            )
            record(tmp_path, "ocr-ambiguous", result_record(batch), image)
            assert batch.results[0].status == RecognitionStatus.AMBIGUOUS
            assert {c.text for c in batch.results[0].candidates} == {"123", "456"}
            assert batch.results[1].status == RecognitionStatus.MATCHED
            assert batch.results[2].status == RecognitionStatus.MATCHED
            assert batch.results[2].candidates[0].text == "123"
        finally:
            assert (await facade.aclose()).released

    asyncio.run(run())
