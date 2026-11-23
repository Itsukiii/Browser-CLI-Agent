"""Proof of BCA CDP Target -> MaaFramework CustomController screenshot/click.

Requires pip install -e '.[lite]' and a separately started, isolated
Chromium/Edge CDP endpoint. Only an explicitly specified target can be used.
"""

import argparse
import asyncio
from pathlib import Path

from PIL import Image

from bca.core.browser import BrowserCaptureProvider, BrowserInputProvider, BrowserSession
from bca.lite.bridge import CDPBridge


def run_maa(bridge: CDPBridge, output: Path, click: tuple[int, int] | None) -> None:
    from bca.lite.maa_controller import MaaCDPController

    ctrl = MaaCDPController(bridge)
    job = ctrl.post_connection().wait()
    if not job.succeeded:
        raise RuntimeError("Maa CustomController connection failed")
    frame_job = ctrl.post_screencap().wait()
    if not frame_job.succeeded:
        raise RuntimeError(f"Maa screenshot failed: {bridge.last_error}")
    bgr = frame_job.get()
    if bgr.size == 0:
        raise RuntimeError("Maa screenshot is empty")
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(bgr[:, :, ::-1], mode="RGB").save(output)
    print(f"Maa screenshot captured: {output} ({bgr.shape[1]}x{bgr.shape[0]})")
    if click is not None:
        if not ctrl.post_click(*click).wait().succeeded:
            raise RuntimeError(f"Maa click rejected: {bridge.last_error}")
        print(f"Maa click confirmed at raw image pixel {click}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:9341")
    parser.add_argument("--target-id", required=True, help="explicit CDP Target ID")
    parser.add_argument("--output", type=Path, default=Path(".test-artifacts/lite-maa.png"))
    parser.add_argument("--click", type=int, nargs=2, metavar=("X", "Y"),
                        help="optional click in the returned raw screenshot")
    args = parser.parse_args()
    session = BrowserSession(args.endpoint)
    capture = BrowserCaptureProvider(session)
    input_provider = BrowserInputProvider(session)
    bridge = None
    try:
        await session.connect()
        await session.bind(args.target_id)
        await capture.start()
        await input_provider.start()
        bridge = CDPBridge(loop=asyncio.get_running_loop(), session=session,
                           capture=capture, input_provider=input_provider)
        await asyncio.to_thread(run_maa, bridge, args.output,
                                tuple(args.click) if args.click else None)
    finally:
        if bridge:
            bridge.invalidate()
        await input_provider.close()
        await capture.close()
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
