"""Trusted test-page plugin, deliberately not a general vision SDK."""

from .plugin import PixelPlugin


def create_plugin() -> PixelPlugin:
    return PixelPlugin()
