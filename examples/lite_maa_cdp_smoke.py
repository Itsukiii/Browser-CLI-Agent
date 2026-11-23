"""Maa native screenshot/click against one explicitly selected, owned CDP page."""

import argparse
import asyncio
from pathlib import Path

from PIL import Image

from bca.core.browser import BrowserCaptureProvider, BrowserInputProvider, BrowserSession
from bca.lite.bridge import CDPBridge, run_native


def run_maa(bridge: CDPBridge, output: Path, click: tuple[int, int] | None) -> None:
    from bca.lite.maa_controller import MaaCDPController

    ctrl = MaaCDPController(bridge)
    try:
        if not ctrl.post_connection().wait().succeeded:
            raise RuntimeError("Maa CustomController connection failed")
        frame_job = ctrl.post_screencap().wait()
        if not frame_job.succeeded:
            raise RuntimeError(f"Maa screenshot failed: {bridge.last_error}")
        bgr = frame_job.get()
        if bgr.size == 0:
            raise RuntimeError("Maa screenshot is empty")
        output.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(bgr[:, :, ::-1]).save(output)
        print(f"Maa screenshot: {output} ({bgr.shape[1]}x{bgr.shape[0]})")
        if click is not None:
            if not ctrl.post_click(*click).wait().succeeded:
                raise RuntimeError(f"Maa click rejected: {bridge.last_error}")
            print(f"Input confirmed at returned screenshot pixel {click}; verify page effect")
    finally:
        ctrl.close()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:9341")
    parser.add_argument("--target-id", required=True, help="explicit CDP Target ID")
    parser.add_argument("--output", type=Path, default=Path(".test-artifacts/lite-maa.png"))
    parser.add_argument(
        "--click",
        type=int,
        nargs=2,
        metavar=("X", "Y"),
        help="optional click in returned screenshot pixels (raw by default)",
    )
    args = parser.parse_args()
    session = BrowserSession(args.endpoint)
    capture = BrowserCaptureProvider(session)
    inputs = BrowserInputProvider(session)
    bridge = None
    try:
        await session.connect()
        await session.bind(args.target_id)
        await capture.start()
        await inputs.start()
        bridge = CDPBridge(
            loop=asyncio.get_running_loop(), session=session, capture=capture, input_provider=inputs
        )
        active = bridge
        await run_native(
            active,
            lambda: run_maa(
                active, args.output, (args.click[0], args.click[1]) if args.click else None
            ),
        )
    finally:

        async def cleanup() -> None:
            if bridge is not None:
                await bridge.aclose()
            try:
                await inputs.close()
            finally:
                try:
                    await capture.close()
                finally:
                    await session.close()

        task = asyncio.create_task(cleanup())
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        task.result()


if __name__ == "__main__":
    asyncio.run(main())
