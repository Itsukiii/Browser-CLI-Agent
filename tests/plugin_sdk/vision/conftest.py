import json
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from bca.core.protocol import Frame, ImageFormat, Viewport
from bca.plugin_sdk.assets import AssetStore

FIXTURES = Path(__file__).parent / "fixtures"


def frame_of(image, *, format="PNG", viewport=None):
    if isinstance(image, np.ndarray):
        image = Image.fromarray(image)
    data = BytesIO()
    image.save(data, format=format, quality=98, subsampling=0)
    return Frame(
        width=image.width,
        height=image.height,
        data=data.getvalue(),
        format=ImageFormat.PNG if format == "PNG" else ImageFormat.JPEG,
        page_id="fixture",
        viewport=viewport
        or Viewport(
            width=image.width,
            height=image.height,
            capture_width=image.width,
            capture_height=image.height,
        ),
    )


@pytest.fixture
def make_template(tmp_path):
    stores = []

    def create(pixels, mask=None):
        root = tmp_path / str(len(stores))
        root.mkdir()
        Image.fromarray(pixels).save(root / "texture.png")
        variant = {"path": "texture.png"}
        if mask is not None:
            Image.fromarray(mask).save(root / "mask.png")
            variant["mask"] = "mask.png"
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "assets": [
                        {
                            "id": "ui.target",
                            "default_variant": "base",
                            "variants": {"base": variant},
                        }
                    ],
                }
            )
        )
        store = AssetStore(root)
        stores.append(store)
        return store.load("ui.target")

    yield create
    for store in stores:
        store.close()
