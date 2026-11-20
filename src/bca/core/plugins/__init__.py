"""Plugin contracts and trusted local plugin composition."""

from .capture_adapter import FreshnessCaptureAdapter
from .catalog import PluginCatalog
from .contracts import Plugin, PluginConfig, PluginContext, PluginMetadata
from .errors import (
    PluginCompatibilityError,
    PluginContractError,
    PluginDuplicateIdError,
    PluginLoadError,
    PluginManifestError,
)
from .host import PluginRuntimeHost
from .loader import PluginLoader
from .lookup import ProviderLookupView
from .manager import PluginManager
from .models import (
    CatalogSnapshot,
    PluginDescriptor,
    PluginDiscoveryIssue,
    PluginLifecycleState,
    PluginSnapshot,
)

__all__ = [
    "Plugin",
    "PluginConfig",
    "PluginContext",
    "PluginMetadata",
    "PluginCatalog",
    "PluginLoader",
    "CatalogSnapshot",
    "PluginDescriptor",
    "PluginDiscoveryIssue",
    "PluginLifecycleState",
    "PluginSnapshot",
    "PluginManifestError",
    "PluginDuplicateIdError",
    "PluginLoadError",
    "PluginCompatibilityError",
    "PluginContractError",
    "PluginManager",
    "ProviderLookupView",
    "FreshnessCaptureAdapter",
    "PluginRuntimeHost",
]
