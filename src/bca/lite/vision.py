"""Single-owner native vision facade. Borrowed CDP providers remain application-owned."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import TypeVar

from ._native_vision import NativeVision
from .bridge import CDPBridge
from .vision_resources import ResourceSpec
from .vision_types import (
    CaptureContext,
    CloseReport,
    RecognitionBatch,
    RecognitionRequest,
    RecognitionStatus,
    VisionError,
)

T = TypeVar("T")


class MaaVisionFacade:
    """One native worker and one serialized capture/recognition transaction.

    Owns Controller/Resource/Tasker. Cancellation retires the facade and bridge,
    drains native work, then propagates cancellation. Always await aclose before
    closing the application's providers. No polling, plugin dispatch or actions.
    """

    def __init__(self, bridge: CDPBridge, resources: ResourceSpec, *, raw_size: bool = True):
        self._loop = asyncio.get_running_loop()
        self._bridge, self._resources, self._raw_size = bridge, resources, raw_size
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bca-maa-vision")
        self._lock = asyncio.Lock()
        self._native: NativeVision | None = None
        self._ready = False
        self._stopping = False
        self._close_task: asyncio.Task[CloseReport] | None = None
        self.close_report: CloseReport | None = None
        self._last_batch: RecognitionBatch | None = None

    @property
    def connected(self) -> bool:
        return self._bridge.connected and not self._stopping

    @property
    def resources(self) -> ResourceSpec:
        return self._resources

    def invalidate(self) -> None:
        self._stopping = True
        self._bridge.invalidate()

    def _owner(self) -> None:
        if asyncio.get_running_loop() is not self._loop:
            raise VisionError("facade requires its owner event loop")

    async def _submit(self, operation: Callable[[], T]) -> T:
        future = self._loop.run_in_executor(self._executor, operation)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            self._stopping = True
            self._bridge.invalidate()
            while not future.done():
                try:
                    await asyncio.shield(future)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not future.cancelled():
                future.exception()
            raise

    async def start(self) -> None:
        self._owner()
        try:
            async with self._lock:
                if self._stopping:
                    raise VisionError("facade is closing or retired")
                if self._ready:
                    return

                def initialize() -> None:
                    self._native = NativeVision(self._bridge, self._resources, self._raw_size)
                    self._native.start()

                await self._submit(initialize)
                if self._stopping:
                    raise VisionError("facade closed during startup")
                self._ready = True
        except BaseException:
            await self.aclose()
            raise

    async def recognize(
        self,
        requests: tuple[RecognitionRequest, ...]
        | Callable[[tuple[int, int]], tuple[RecognitionRequest, ...]],
    ) -> RecognitionBatch:
        """Take exactly one fresh Maa screenshot and recognize all requests on it."""
        self._owner()
        async with self._lock:
            if not self._ready or self._stopping or self._native is None:
                raise VisionError("facade is not running")
            native = self._native
            image = await self._submit(native.capture)
            ref = self._bridge.observation
            if ref is None:
                raise VisionError("capture lost its bridge observation")
            context = CaptureContext(
                ref, self._bridge.binding, image.shape[1], image.shape[0], image.tobytes()
            )
            requests = tuple(
                requests((context.width, context.height)) if callable(requests) else requests
            )
            if not requests or len({r.key for r in requests}) != len(requests):
                raise ValueError("nonempty requests with distinct keys required")
            for request in requests:
                if not request.key or not math.isfinite(request.threshold):
                    raise ValueError("invalid recognition key/threshold")
                if not 0 <= request.threshold <= 1:
                    raise ValueError("threshold must be between zero and one")
                if request.roi is not None:
                    x, y, w, h = request.roi
                    if any(type(v) is not int for v in request.roi) or not (
                        x >= 0
                        and y >= 0
                        and w > 0
                        and h > 0
                        and x + w <= context.width
                        and y + h <= context.height
                    ):
                        raise ValueError("ROI must be inside the Maa returned image")
            results = await self._submit(
                lambda: tuple(native.recognize(r, context.image) for r in requests)
            )
            current = self._bridge.observation is ref and not self._stopping
            completed = time.monotonic()
            if not current:
                results = tuple(
                    replace(
                        r,
                        status=RecognitionStatus.ERROR,
                        diagnostic="observation replaced or binding retired",
                    )
                    for r in results
                )
            batch = RecognitionBatch(
                context,
                results,
                completed,
                current,
                completed - ref.observed_at > self._bridge.max_frame_age,
            )
            self._last_batch = batch
            return batch

    async def click(self, batch: RecognitionBatch, request_key: str, candidate_index: int) -> str:
        """Coordinator-only: exact latest batch, unique candidate, fresh one-shot authorization."""
        self._owner()
        async with self._lock:
            if (
                not self.connected
                or self._native is None
                or not self._bridge.requires_authorization
            ):
                raise VisionError("click requires live explicitly authorized composition")
            if batch is not self._last_batch or not batch.source_current or batch.expired:
                raise VisionError("not the current issued batch")
            matches = [r for r in batch.results if r.request_key == request_key]
            if len(matches) != 1 or matches[0].status != RecognitionStatus.MATCHED:
                raise VisionError("target recognition is not matched")
            candidates = matches[0].candidates
            if len(candidates) != 1 or candidate_index != 0:
                raise VisionError("target must be a unique visual candidate")
            x, y, w, h = candidates[0].box
            point = (x + (w - 1) // 2, y + (h - 1) // 2)
            context = batch.capture
            frame = context.source_ref.frame
            raw = tuple(
                math.floor(p * size / returned + 0.5)
                for p, size, returned in zip(
                    point, (frame.width, frame.height), (context.width, context.height), strict=True
                )
            )
            if not (0 <= raw[0] < frame.width and 0 <= raw[1] < frame.height):
                raise VisionError("mapped native point outside Frame")
            await self._bridge.authorize(context.source_ref)
            self._last_batch = None
            controller = self._native.controller
            assert controller is not None
            await self._submit(lambda: controller.post_click(*point).wait().succeeded)
            return self._bridge.input_outcome

    async def _close(self) -> CloseReport:
        async with self._lock:
            if self._native is not None:
                report = await self._submit(self._native.close)
            else:
                report = CloseReport(True, None, (), ())
            self.close_report = report
            self._ready = False
            if report.released:
                await self._bridge.aclose()
                await asyncio.to_thread(self._executor.shutdown, wait=True)
            elif self._native is not None and self._native._destroy_uncertain:
                self._bridge.invalidate()
                await asyncio.to_thread(self._executor.shutdown, wait=True)
            return report

    async def aclose(self) -> CloseReport:
        """Idempotent shared close, shielded against repeated caller cancellation."""
        self._owner()
        if self._close_task is not None and self._close_task.done():
            previous = self._close_task.result()
            if not previous.released and not (
                self._native is not None and self._native._destroy_uncertain
            ):
                self._close_task = None  # Retry on the same owning worker, retaining handles.
        if self._close_task is None:
            self._stopping = True
            self._close_task = asyncio.create_task(self._close())
        cancelled = False
        while not self._close_task.done():
            try:
                await asyncio.shield(self._close_task)
            except asyncio.CancelledError:
                cancelled = True
        result = self._close_task.result()
        if cancelled:
            raise asyncio.CancelledError
        return result
