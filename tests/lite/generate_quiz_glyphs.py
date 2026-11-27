"""Original CC0 digit strokes. Asset rendering only; no recognition algorithm."""

import hashlib
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

# Original coordinate paths in a 64x96 cell, no font file or captured pixels.
PATHS = {
    0: [
        [
            (32, 12),
            (20, 15),
            (13, 30),
            (13, 66),
            (20, 81),
            (32, 84),
            (44, 81),
            (51, 66),
            (51, 30),
            (44, 15),
            (32, 12),
        ]
    ],
    1: [[(17, 28), (32, 12), (32, 84)], [(16, 84), (48, 84)]],
    2: [
        [
            (13, 27),
            (18, 17),
            (29, 12),
            (42, 15),
            (51, 25),
            (50, 38),
            (42, 49),
            (13, 81),
            (13, 84),
            (52, 84),
        ]
    ],
    3: [
        [(13, 19), (28, 12), (42, 15), (50, 25), (48, 37), (37, 46), (26, 46)],
        [(37, 46), (49, 55), (51, 68), (44, 80), (30, 84), (14, 78)],
    ],
    4: [[(42, 84), (42, 12), (10, 62), (55, 62)]],
    5: [
        [
            (51, 12),
            (17, 12),
            (14, 45),
            (30, 41),
            (44, 46),
            (51, 58),
            (50, 72),
            (40, 82),
            (27, 84),
            (13, 77),
        ]
    ],
    6: [
        [
            (48, 16),
            (35, 12),
            (22, 20),
            (14, 37),
            (12, 64),
            (18, 78),
            (30, 84),
            (44, 79),
            (51, 67),
            (48, 54),
            (37, 46),
            (24, 47),
            (13, 57),
        ]
    ],
    7: [[(12, 12), (52, 12), (24, 84)]],
    8: [
        [(32, 12), (19, 16), (13, 27), (17, 39), (32, 48), (47, 39), (51, 27), (45, 16), (32, 12)],
        [(32, 48), (17, 55), (12, 68), (18, 80), (32, 84), (46, 80), (52, 68), (47, 55), (32, 48)],
    ],
    9: [
        [
            (51, 40),
            (42, 49),
            (28, 50),
            (16, 42),
            (12, 28),
            (20, 15),
            (34, 12),
            (46, 19),
            (52, 35),
            (50, 60),
            (42, 77),
            (30, 84),
            (16, 80),
        ]
    ],
}


def render(digit, weight="normal", height=96):
    supersample = 4
    image = Image.new("RGB", (64 * supersample, 96 * supersample), "white")
    draw = ImageDraw.Draw(image)
    width = (6 if weight == "normal" else 8) * supersample
    for path in PATHS[digit]:
        draw.line(
            [(x * supersample, y * supersample) for x, y in path],
            fill="#15243d",
            width=width,
            joint="curve",
        )
    return image.resize((round(height * 2 / 3), height), Image.Resampling.LANCZOS)


def generate(directory):
    directory.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for weight in ("normal", "bold"):
        for digit in range(10):
            path = directory / f"glyph-{weight}-{digit}.png"
            render(digit, weight).save(path)
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (directory.parent / "glyphs.json").write_text(
        json.dumps(
            {
                "license": "CC0-1.0",
                "source": "original coordinate paths in generate_quiz_glyphs.py",
                "canvas": [64, 96],
                "sha256": hashes,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    generate(Path(sys.argv[1]))
