"""Deterministic owned images; no DOM or production recognition implementation."""

import asyncio
import json
from io import BytesIO

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from bca.core.protocol import Frame, ImageFormat, Viewport
from bca.lite.bridge import CDPBridge
from tests.lite.test_cdp_bridge import FakeInput, FakeSession


def marker():
    pixels = np.random.default_rng(20261124).integers(0, 256, (28, 36, 3), dtype=np.uint8)
    return Image.fromarray(pixels)


def scene(text="123", points=((60, 50),)):
    image = Image.new("RGB", (480, 240), "white")
    for point in points:
        image.paste(marker(), point)
    ImageDraw.Draw(image).text((80, 130), text, fill="black", font=ImageFont.load_default(48))
    return image


class ImageCapture:
    available = True

    def __init__(self, image):
        self.image = image
        self.count = 0

    async def capture(self, page_id):
        self.count += 1
        buf = BytesIO()
        self.image.save(buf, format="PNG")
        w, h = self.image.size
        return Frame(
            width=w,
            height=h,
            data=buf.getvalue(),
            format=ImageFormat.PNG,
            viewport=Viewport(width=w, height=h, capture_width=w, capture_height=h),
            page_id=page_id,
            session_id="session-one",
        )


def bridge_for(monkeypatch, image, **kwargs):
    monkeypatch.setattr("bca.lite.bridge.measure_geometry", lambda s: asyncio.sleep(0, result="g"))
    capture, session, inputs = ImageCapture(image), FakeSession(), FakeInput()
    bridge = CDPBridge(
        loop=asyncio.get_running_loop(),
        session=session,
        capture=capture,
        input_provider=inputs,
        require_authorization=True,
        **kwargs,
    )
    return bridge, capture, session, inputs


def bundle_at(path):
    (path / "image").mkdir(parents=True)
    (path / "pipeline").mkdir()
    marker().save(path / "image/marker.png")
    (path / "pipeline/fixture.json").write_text(
        json.dumps(
            {
                "TemplateProbe": {
                    "recognition": "TemplateMatch",
                    "template": "marker.png",
                    "roi": [40, 30, 150, 80],
                    "action": "DoNothing",
                    "timeout": 100,
                },
                "OCRProbe": {
                    "recognition": "OCR",
                    "roi": [50, 100, 350, 110],
                    "action": "DoNothing",
                    "timeout": 100,
                },
            }
        ),
        encoding="utf-8",
    )
    return path.resolve()
