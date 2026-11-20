"""Deterministic, browser-free AssetStore example with two independent profiles.

Run with the assets extra installed: python examples/asset_foundation.py
All files are owned by a temporary directory; no repository fixture dependency.
"""

import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from bca.plugin_sdk.assets import AssetStore


def run() -> None:
    with TemporaryDirectory(prefix="bca-assets-") as directory:
        root = Path(directory)
        for name, color in (("light", (240, 240, 240)), ("dark", (16, 24, 32))):
            with Image.new("RGB", (2, 1), color) as image:
                image.save(root / f"{name}.png")
            (root / f"{name}.ini").write_text(
                f"[profile]\nname={name}\ntheme={name}\ndefault_scene=dialog\n", encoding="utf-8"
            )
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "assets": [
                        {
                            "id": "ui.confirm",
                            "default_variant": "dialog.light",
                            "variants": {
                                name: {
                                    "path": f"{theme}.png",
                                    "scene": "dialog",
                                    "theme": theme,
                                    "size": [2, 1],
                                }
                                for name, theme in (
                                    ("dialog.light", "light"),
                                    ("dialog.dark", "dark"),
                                )
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        for profile in ("light", "dark"):
            store = AssetStore(root, profile=Path(f"{profile}.ini"))
            try:
                selection = store.resolve("ui.confirm")
                template = store.load("ui.confirm")
                assert store.load("ui.confirm") is template
                print(
                    json.dumps(
                        {
                            "profile": store.profile.name,
                            "ids": store.ids(),
                            "variants": store.variants("ui.confirm"),
                            "selected": selection.variant_id,
                            "rgb": template.image.tolist(),
                            "writeable": template.image.flags.writeable,
                            "cache": asdict(store.cache_info()),
                        }
                    )
                )
            finally:
                store.close()
            assert template.image.shape == (1, 2, 3)  # caller retains immutable pixels


if __name__ == "__main__":
    run()
