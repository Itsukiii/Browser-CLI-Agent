"""Rebuild deterministic inputs from placement rules, never from matcher outputs."""

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent


def main():
    rng = np.random.default_rng(7042)
    pixels = np.repeat(np.repeat(rng.integers(0, 256, (3, 4, 3), dtype=np.uint8), 4, 0), 4, 1)
    texture = Image.fromarray(pixels)
    texture.save(ROOT / "texture.png")
    alpha = np.full((12, 16), 255, np.uint8)
    alpha[:, :4] = 128
    Image.fromarray(np.dstack((pixels, alpha))).save(ROOT / "alpha.png")
    mask = np.tile(np.repeat(np.array([0, 64, 128, 255], np.uint8), 4), (12, 1))
    Image.fromarray(mask).save(ROOT / "mask.png")
    variants = {
        "base": {"path": "texture.png"},
        "weighted": {"path": "alpha.png", "mask": "mask.png"},
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "assets": [
                    {"id": "ui.target", "default_variant": "base", "variants": variants},
                    {
                        "id": "ui.rival",
                        "default_variant": "base",
                        "variants": {"base": variants["base"]},
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (ROOT / "weighted.ini").write_text(
        "[profile]\nname=weighted\n[variants]\nui.target=weighted\n", encoding="utf-8"
    )
    cases = []
    # Expected bboxes are placement labels, independent of the matching implementation.
    for group in ("rgb", "gray", "mask", "enlarge", "shrink", "anisotropic", "jpeg", "roi"):
        scale = {"enlarge": (2, 2), "shrink": (0.5, 0.5), "anisotropic": (1.5, 0.5)}.get(
            group, (1, 1)
        )
        width, height = int(16 * scale[0]), int(12 * scale[1])
        resized = texture.resize(
            (width, height),
            Image.Resampling.BOX if group == "shrink" else Image.Resampling.BILINEAR,
        )
        for i in range(4):
            x, y = 20 + i * 7, 14 + i * 6
            for positive in (True, False):
                name = f"{group}-{'positive' if positive else 'negative'}-{i}"
                screen = Image.new("RGB", (128, 96), (96 + i * 8,) * 3)
                if positive:
                    screen.paste(resized, (x, y))
                else:
                    # Reversed asymmetric object is a distractor with independent negative label.
                    screen.paste(resized.transpose(Image.Transpose.FLIP_LEFT_RIGHT), (x, y))
                extension = "jpg" if group == "jpeg" else "png"
                screen.save(ROOT / f"{name}.{extension}", quality=98, subsampling=0)
                cases.append(
                    {
                        "name": name,
                        "group": group,
                        "image": f"{name}.{extension}",
                        "status": "matched" if positive else "not_found",
                        "bboxes": [[x, y, width, height]] if positive else [],
                        "scale": scale,
                        "mode": "gray" if group == "gray" else "rgb",
                        "profile": "weighted.ini" if group == "mask" else None,
                        "roi": [12, 8, 96, 72] if group == "roi" else None,
                    }
                )
    for kind in ("ambiguous", "repeated"):
        for i in range(6):
            name = f"{kind}-{i}"
            screen = Image.new("RGB", (128, 96), (100, 100, 100))
            boxes = [[10 + i, 12, 16, 12]]
            if kind == "repeated":
                boxes.append([80, 60 + i, 16, 12])
            for x, y, _w, _h in boxes:
                screen.paste(texture, (x, y))
            screen.save(ROOT / f"{name}.png")
            cases.append(
                {
                    "name": name,
                    "group": kind,
                    "image": f"{name}.png",
                    "status": "ambiguous" if kind == "ambiguous" else "matched",
                    "bboxes": boxes,
                    "scale": [1, 1],
                    "mode": "rgb",
                    "profile": None,
                    "roi": None,
                }
            )
    (ROOT / "expected.json").write_text(
        json.dumps(
            {
                "threshold": 0.96,
                "label_source": "known placement, never matcher output",
                "mask_effective_first_row": [0] * 4 + [64] * 4 + [128] * 4 + [255] * 4,
                "cases": cases,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
