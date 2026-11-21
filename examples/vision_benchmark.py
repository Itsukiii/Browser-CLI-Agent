"""Reproducible offline timing and bounded repeated-call memory samples."""

import argparse
import ctypes
import json
import math
import os
import platform
import sys
import tracemalloc
from collections import defaultdict
from dataclasses import asdict, replace
from io import BytesIO
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter, process_time
from typing import Any

import cv2
import numpy as np
from PIL import Image

from bca.core.protocol import Frame, ImageFormat, Viewport
from bca.plugin_sdk.assets import AssetStore
from bca.plugin_sdk.vision import MatchOptions, PixelRect, PreprocessMode, match_frame

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from examples.plugins.vision_fixture.assets import create_assets  # noqa: E402


class Counters(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_uint32), ("faults", ctypes.c_uint32)] + [
        (name, ctypes.c_size_t)
        for name in (
            "peak_working_set",
            "working_set",
            "peak_paged",
            "paged",
            "peak_nonpaged",
            "nonpaged",
            "pagefile",
            "peak_pagefile",
        )
    ]


def memory_bytes() -> int | None:
    """Windows current working set; includes native allocations, not Python-only tracing."""
    if os.name != "nt":
        return None

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    success = ctypes.windll.psapi.GetProcessMemoryInfo(
        ctypes.c_void_p(-1), ctypes.byref(counters), counters.cb
    )
    return int(counters.working_set) if success else None


def run(output: Path, samples: int = 30) -> dict[str, Any]:
    if samples < 1:
        raise ValueError("samples must be positive")
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "numpy": np.__version__,
        "opencv": cv2.__version__,
        "opencv_threads": cv2.getNumThreads(),
        "samples": samples,
        "warmup": 3,
        "p95": "sorted[ceil(n*.95)-1]",
        "cases": [],
    }
    with TemporaryDirectory(prefix="bca-vision-benchmark-") as directory:
        root = Path(directory)
        create_assets(root)
        store = AssetStore(root)
        try:
            template = store.load("ui.idle")
            screen = Image.new("RGB", (640, 480), (128, 128, 128))
            screen.paste(Image.fromarray(template.image), (80, 70))
            encoded = BytesIO()
            screen.save(encoded, format="PNG")
            frame = Frame(
                width=640,
                height=480,
                data=encoded.getvalue(),
                format=ImageFormat.PNG,
                page_id="benchmark",
                viewport=Viewport(width=640, height=480, capture_width=640, capture_height=480),
            )
            roi = PixelRect(x=60, y=50, width=240, height=180)
            mask = np.frombuffer(bytes([64, 128, 255, 0]) * (32 * 24 // 4), np.uint8).reshape(
                24, 32
            )
            many = tuple(
                replace(
                    template,
                    asset_id=f"ui.target{i}",
                    selection=replace(template.selection, asset_id=f"ui.target{i}"),
                )
                for i in range(4)
            )
            cases = [
                ("full_one", (template,), MatchOptions()),
                ("roi_one", (template,), MatchOptions(roi=roi)),
                ("full_four", many, MatchOptions()),
                (
                    "roi_multiscale",
                    (template,),
                    MatchOptions(roi=roi, scales=((0.5, 0.5), (1, 1), (1.5, 1.5), (2, 2))),
                ),
                ("full_mask", (replace(template, mask=mask),), MatchOptions()),
                ("roi_gray", (template,), MatchOptions(roi=roi, mode=PreprocessMode.GRAY)),
            ]
            for name, templates, options in cases:
                for _ in range(3):
                    match_frame(frame, templates, options=options)
                measurements: dict[str, list[float]] = defaultdict(list)
                cpu_start, wall_start = process_time(), perf_counter()
                rss_before = memory_bytes()
                for _ in range(samples):
                    result = match_frame(frame, templates, options=options)
                    for field, value in asdict(result.timing).items():
                        measurements[field].append(value)
                elapsed, cpu = perf_counter() - wall_start, process_time() - cpu_start
                report["cases"].append(
                    {
                        "name": name,
                        "frame": [640, 480],
                        "roi": asdict(options.roi) if options.roi else None,
                        "templates": len(templates),
                        "template_size": [32, 24],
                        "scales": options.scales,
                        "mask": templates[0].mask is not None,
                        "mode": options.mode.value,
                        "raw": measurements,
                        "summary": {
                            field: {
                                "median_ms": median(values),
                                "p95_ms": sorted(values)[math.ceil(len(values) * 0.95) - 1],
                            }
                            for field, values in measurements.items()
                        },
                        "wall_seconds": elapsed,
                        "cpu_seconds": cpu,
                        "cpu_one_core_percent": 100 * cpu / elapsed,
                        "rss_before": rss_before,
                        "rss_after": memory_bytes(),
                    }
                )
            # Separate instrumentation run, so tracemalloc doesn't distort the timings above.
            tracemalloc.start()
            memory_samples = []
            start = perf_counter()
            for i in range(101):
                match_frame(frame, (template,), options=MatchOptions(roi=roi))
                if i % 10 == 0:
                    current, peak = tracemalloc.get_traced_memory()
                    memory_samples.append(
                        {
                            "iteration": i,
                            "python_bytes": current,
                            "python_peak_bytes": peak,
                            "windows_working_set": memory_bytes(),
                        }
                    )
            report["memory_run"] = {
                "seconds": perf_counter() - start,
                "calls": 101,
                "samples": memory_samples,
                "scope": "tracemalloc Python; PSAPI process working set",
            }
            tracemalloc.stop()
        finally:
            store.close()
    (output / "offline.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(".test-artifacts/04.2/performance"))
    parser.add_argument("--samples", type=int, default=30)
    args = parser.parse_args()
    report = run(args.output, args.samples)
    print(json.dumps({c["name"]: c["summary"]["total_ms"] for c in report["cases"]}))
