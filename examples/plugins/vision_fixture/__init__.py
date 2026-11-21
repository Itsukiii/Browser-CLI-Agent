"""Controlled visual integration plugin, not a production game recognizer."""

from .plugin import VisionPlugin

__all__ = ["VisionPlugin"]


def create_plugin() -> VisionPlugin:
    return VisionPlugin()
