"""Plugin-system errors; messages deliberately exclude plugin exception payloads."""

from bca.core.errors import PluginError


class PluginManifestError(PluginError):
    code = "plugin.manifest"


class PluginDuplicateIdError(PluginManifestError):
    code = "plugin.duplicate_id"


class PluginLoadError(PluginError):
    code = "plugin.load"


class PluginCompatibilityError(PluginError):
    code = "plugin.compatibility"


class PluginContractError(PluginError):
    code = "plugin.contract"
