"""Test-only fault launcher. Not installed as a product entry point."""

import sys

from bca.lite._native_vision import NativeVision
from bca.lite.cli import main
from bca.lite.vision_types import CloseReport

mode = sys.argv.pop(1)
if mode == "stop_failed":

    def failed(self):
        print("INJECTION stop failed; no Destroy", flush=True)
        return CloseReport(False, self.thread, (), ("injected stop failure",), "failed")

    NativeVision.close = failed
elif mode == "pre_click_failed":
    from types import SimpleNamespace

    from bca.lite.maa_controller import MaaCDPController

    def failed_click(self, *args):
        print("INJECTION native job failed before Bridge.click", flush=True)
        return SimpleNamespace(wait=lambda: SimpleNamespace(succeeded=False))

    MaaCDPController.post_click = failed_click
else:
    raise ValueError(mode)

raise SystemExit(main())
