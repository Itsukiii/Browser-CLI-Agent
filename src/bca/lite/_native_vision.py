"""Audited maafw 5.16.1 boundary. All methods run on one owning worker."""

from __future__ import annotations

import importlib.metadata
import json
import math
import threading
from typing import Any

import numpy as np
from maa.library import Library  # type: ignore[import-untyped]
from maa.pipeline import JOCR, JTemplateMatch  # type: ignore[import-untyped]
from maa.resource import Resource  # type: ignore[import-untyped]
from maa.tasker import Tasker  # type: ignore[import-untyped]
from numpy.typing import NDArray
from PIL import Image

from .bridge import CDPBridge
from .maa_controller import MaaCDPController
from .vision_resources import ResourceSpec, template_path
from .vision_types import (
    Candidate,
    CloseReport,
    OCRRequest,
    RecognitionRequest,
    RecognitionResult,
    RecognitionStatus,
    TemplateRequest,
    VisionError,
)


def _candidate(value: Any, width: int, height: int, algorithm: str) -> Candidate:
    box = value.box
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise VisionError("unexpected candidate box")
    x, y, w, h = box
    if any(type(v) is not int for v in box) or not (
        x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= width and y + h <= height
    ):
        raise VisionError("candidate outside Maa image")
    score = float(value.score)
    if not math.isfinite(score):
        raise VisionError("nonfinite recognition score")
    text = value.text if algorithm == "OCR" else None
    if algorithm == "OCR" and not isinstance(text, str):
        raise VisionError("invalid OCR text")
    return Candidate((x, y, w, h), score, text)


def normalize(job: Any, request: RecognitionRequest, width: int, height: int) -> RecognitionResult:
    """Materialize lazy details before Destroy; keep native failure separate from miss."""
    algorithm = "OCR" if isinstance(request, OCRRequest) else "TemplateMatch"
    status = "succeeded" if job.succeeded else "failed" if job.failed else "invalid"
    meta: dict[str, Any] = {
        "request_key": request.key,
        "algorithm": algorithm,
        "job_id": int(job.job_id),
        "job_status": status,
    }
    try:
        task = job.get()
        if task is None or len(task.nodes) != 1:
            raise VisionError("expected one materializable direct-recognition node")
        reco = task.nodes[0].recognition
        if reco is None or reco.algorithm != algorithm or type(reco.hit) is not bool:
            raise VisionError("recognition algorithm/details mismatch")
        meta.update(
            reco_id=int(reco.reco_id),
            hit=reco.hit,
            raw_detail_json=json.dumps(reco.raw_detail, ensure_ascii=False, allow_nan=False),
        )
        if not {"all", "filtered", "best"}.issubset(reco.raw_detail):
            raise VisionError("incomplete native recognition detail")
        if status != "succeeded":
            raise VisionError("native recognition job did not succeed")
        all_candidates = tuple(_candidate(c, width, height, algorithm) for c in reco.all_results)
        candidates = tuple(_candidate(c, width, height, algorithm) for c in reco.filtered_results)
        best = _candidate(reco.best_result, width, height, algorithm) if reco.best_result else None
        if any(c not in all_candidates for c in candidates):
            raise VisionError("filtered candidate missing from native all results")
        if reco.hit:
            if status != "succeeded" or not candidates or best not in candidates:
                raise VisionError("inconsistent hit/job/candidates")
            result_status = (
                RecognitionStatus.AMBIGUOUS
                if request.unique and len(candidates) != 1
                else RecognitionStatus.MATCHED
            )
        else:
            if candidates or best is not None or reco.box is not None:
                raise VisionError("inconsistent no-hit detail")
            result_status = RecognitionStatus.NOT_FOUND
        return RecognitionResult(
            status=result_status,
            candidates=candidates,
            all_candidates=all_candidates,
            best=best,
            **meta,
        )
    except Exception as exc:
        return RecognitionResult(status=RecognitionStatus.ERROR, diagnostic=str(exc), **meta)


class NativeVision:
    def __init__(self, bridge: CDPBridge, spec: ResourceSpec, raw_size: bool) -> None:
        self.thread = threading.get_ident()
        self.bridge, self.spec, self.raw_size = bridge, spec, raw_size
        self.controller: MaaCDPController | None = None
        self.resource: Any = None
        self.tasker: Any = None
        self.destroyed: list[str] = []
        self.ocr_loaded = False

    def _check_thread(self) -> None:
        if threading.get_ident() != self.thread:
            raise VisionError("native object used outside owning worker")

    def start(self) -> None:
        self._check_thread()
        if (
            importlib.metadata.version("maafw") not in ("5.16.1", "v5.16.1")
            or Library.version() != "v5.16.1"
        ):
            raise VisionError("native lifetime adapter requires Python/native Maa v5.16.1")
        bundle = self.spec.bundle_path()
        model = self.spec.ocr.verify() if self.spec.ocr else None
        self.controller = MaaCDPController(self.bridge, raw_size=self.raw_size)
        if not self.controller.post_connection().wait().succeeded:
            raise VisionError("native controller connection failed")
        self.resource = Resource()
        if not self.resource.post_bundle(bundle).wait().succeeded:
            raise VisionError("Maa resource bundle load failed")
        if model is not None:
            if not self.resource.post_ocr_model(model).wait().succeeded:
                raise VisionError("Maa OCR model load failed after checksum verification")
            self.ocr_loaded = True
        self.tasker = Tasker()
        if not self.tasker.bind(self.resource, self.controller) or not self.tasker.inited:
            raise VisionError("Maa tasker binding failed")

    def capture(self) -> NDArray[np.uint8]:
        self._check_thread()
        assert self.controller is not None
        job = self.controller.post_screencap().wait()
        if not job.succeeded:
            raise VisionError(f"native screenshot failed: {self.bridge.last_error}")
        image: NDArray[np.uint8] = job.get()
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3 or not image.size:
            raise VisionError("invalid Maa BGR screenshot")
        return image.copy()

    def recognize(self, request: RecognitionRequest, image: NDArray[np.uint8]) -> RecognitionResult:
        self._check_thread()
        algorithm = "TemplateMatch" if isinstance(request, TemplateRequest) else "OCR"
        try:
            roi = request.roi or (0, 0, 0, 0)
            if isinstance(request, TemplateRequest):
                path = template_path(self.spec.bundle, request.template)
                with Image.open(path) as template:
                    width, height = request.roi[2:] if request.roi else image.shape[1::-1]
                    if template.width > width or template.height > height:
                        raise VisionError("template exceeds recognition ROI")
                param = JTemplateMatch(
                    template=[request.template], roi=roi, threshold=[request.threshold]
                )
            else:
                if not self.ocr_loaded:
                    raise VisionError("OCR model not explicitly loaded")
                param = JOCR(
                    roi=roi,
                    threshold=request.threshold,
                    expected=list(request.expected),
                    only_rec=request.only_rec,
                )
            job = self.tasker.post_recognition(algorithm, param, image).wait()
            return normalize(job, request, image.shape[1], image.shape[0])
        except Exception as exc:
            return RecognitionResult(
                request.key, algorithm, RecognitionStatus.ERROR, diagnostic=str(exc)
            )

    def close(self) -> CloseReport:
        self._check_thread()
        errors = []
        stop_status = None
        # Do not destroy dependencies if destroying their tasker fails.
        try:
            if self.tasker is not None and self.tasker._handle:
                if self.tasker.inited or self.tasker.running:
                    stop = self.tasker.post_stop().wait()
                    stop_status = "succeeded" if stop.succeeded else "failed"
                else:
                    stop_status = "not_needed_idle_disconnected"
                Library.framework().MaaTaskerDestroy(self.tasker._handle)
                self.tasker._handle = None
                self.destroyed.append("tasker")
            if self.controller is not None and self.controller._handle:
                self.controller.close()
                self.destroyed.append("controller")
            if self.resource is not None and self.resource._handle:
                Library.framework().MaaResourceDestroy(self.resource._handle)
                self.resource._handle = None
                self.destroyed.append("resource")
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        released = not any(
            getattr(o, "_handle", None) for o in (self.tasker, self.controller, self.resource)
        )
        return CloseReport(released, self.thread, tuple(self.destroyed), tuple(errors), stop_status)
