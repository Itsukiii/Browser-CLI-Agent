"""Offline AssetStore -> Frame -> vision -> CSS demonstration; any working directory."""

import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from bca.core.protocol import Frame, ImageFormat, Viewport
from bca.plugin_sdk.assets import AssetStore
from bca.plugin_sdk.vision import decode_frame, match_templates


def main() -> None:
    with TemporaryDirectory(prefix="bca-vision-example-") as directory:
        root = Path(directory)
        texture = Image.new("RGB", (8, 6))
        texture.putdata(
            [(x * 31, y * 43, (x * 29 + y * 37) % 256) for y in range(6) for x in range(8)]
        )
        texture.save(root / "target.png")
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "assets": [
                        {
                            "id": "ui.confirm",
                            "default_variant": "light",
                            "variants": {"light": {"path": "target.png", "theme": "light"}},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (root / "profile.ini").write_text("[profile]\nname=light\ntheme=light\n", encoding="utf-8")
        store = AssetStore(root, profile=Path("profile.ini"))
        try:
            template = store.load("ui.confirm")
            screen = Image.new("RGB", (96, 64), (90, 90, 90))
            screen.paste(texture, (23, 17))
            encoded = BytesIO()
            screen.save(encoded, format="PNG")
            frame = Frame(
                width=96,
                height=64,
                data=encoded.getvalue(),
                format=ImageFormat.PNG,
                page_id="offline",
                viewport=Viewport(
                    width=200,
                    height=100,
                    capture_width=144,
                    capture_height=64,
                    capture_x=10,
                    capture_y=5,
                ),
            )
            decoded = decode_frame(frame)
            rival = replace(
                template,
                asset_id="ui.rival",
                selection=replace(template.selection, asset_id="ui.rival"),
            )
            for templates in ((template,), (template, rival)):
                result = match_templates(decoded, templates)
                c = result.best_candidate
                assert c is not None
                print(
                    json.dumps(
                        {
                            "status": result.status.value,
                            "asset_id": c.asset_id,
                            "variant_id": c.variant_id,
                            "score": c.score,
                            "bbox": [c.bbox.x, c.bbox.y, c.bbox.width, c.bbox.height],
                            "center": c.center,
                            "css": frame.pixel_to_css(*c.center),
                            "action_allowed": result.status.value == "matched",
                        }
                    )
                )
        finally:
            store.close()


if __name__ == "__main__":
    main()
