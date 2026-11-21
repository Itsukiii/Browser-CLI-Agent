"""Deterministic, asymmetric texture assets shared by the fixture page and plugin."""

import json
from pathlib import Path

import numpy as np
from PIL import Image


def create_assets(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    assets = []
    for index, state in enumerate(("idle", "done")):
        variants = {}
        for theme in ("light", "dark"):
            rng = np.random.default_rng(421 + index)
            pixels = rng.integers(0, 256, (6, 8, 3), dtype=np.uint8)
            if theme == "dark":
                pixels = 255 - pixels
            pixels = np.repeat(np.repeat(pixels, 4, axis=0), 4, axis=1)
            name = f"{state}.{theme}.png"
            Image.fromarray(pixels).save(root / name)
            variants[f"panel.{theme}"] = {"path": name, "scene": "panel", "theme": theme}
        assets.append({"id": f"ui.{state}", "default_variant": "panel.light", "variants": variants})
    (root / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "assets": assets}), encoding="utf-8"
    )
    for theme in ("light", "dark"):
        (root / f"{theme}.ini").write_text(
            f"[profile]\nname={theme}\ntheme={theme}\ndefault_scene=panel\n", encoding="utf-8"
        )
