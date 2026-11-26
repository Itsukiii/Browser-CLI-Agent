"""Explicit same-process native/legacy order, fresh process per invocation."""

import importlib.metadata
import json
import os
import platform
import sys
import time

import psutil
import pytest

from tests.lite.stability_probe import sample


def main():
    mode = sys.argv[1]
    groups = {
        "legacy": [
            "tests/plugin_sdk/vision/test_decode.py",
            "tests/plugin_sdk/vision/test_dataset.py",
        ],
        "maa": ["tests/lite/test_vision_native.py", "tests/lite/test_observation.py"],
    }
    print(
        json.dumps(
            {
                "python": platform.python_version(),
                "pid": os.getpid(),
                "mode": mode,
                "packages": {
                    name: importlib.metadata.version(name)
                    for name in ("maafw", "numpy", "opencv-python-headless", "Pillow")
                },
            }
        ),
        flush=True,
    )
    for group in mode.split("-"):
        print(json.dumps({"phase": group + "-before", **sample(psutil.Process())}), flush=True)
        code = pytest.main([*groups[group], "-q"])
        if group == "maa":
            from maa.library import Library

            print(json.dumps({"native_maa": Library.version()}), flush=True)
        print(
            json.dumps(
                {
                    "phase": group + "-after",
                    "exit_code": int(code),
                    "cv2_loaded": "cv2" in sys.modules,
                    "legacy_loaded": "bca.plugin_sdk.vision" in sys.modules,
                    **sample(psutil.Process()),
                }
            ),
            flush=True,
        )
        if code:
            return int(code)
        if mode == "maa":
            assert "cv2" not in sys.modules and "bca.plugin_sdk.vision" not in sys.modules
        time.sleep(0.5)  # External monitor captures post-cleanup plateau.
    return 0


if __name__ == "__main__":
    sys.exit(main())
