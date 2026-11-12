"""Re-export the canonical plugin contract without duplicating it."""

from bca.core.plugins import Plugin, PluginConfig, PluginContext, PluginMetadata

__all__ = ["Plugin", "PluginConfig", "PluginContext", "PluginMetadata"]
