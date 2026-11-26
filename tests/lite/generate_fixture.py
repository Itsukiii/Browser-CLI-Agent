"""Reproduce the original fixture asset; no screenshot or external image input."""

import sys

from PIL import Image, ImageDraw


def marker():
    image = Image.new("RGB", (96, 64), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 95, 63), fill="#192d66")
    draw.rectangle((8, 8, 39, 55), fill="#efbc28")
    draw.ellipse((48, 8, 87, 47), fill="#42ce99")
    draw.rectangle((64, 48, 87, 55), fill="white")
    return image


if __name__ == "__main__":
    marker().save(sys.argv[1])
