"""Validation at trusted Python plugin boundaries."""

import inspect
from typing import cast

from bca.core.errors import CapabilityUnavailableError
from bca.core.protocol import PROTOCOL_VERSION
from bca.core.providers import CaptureProvider, InputProvider, ProviderLookup

from .contracts import Plugin, PluginMetadata
from .errors import PluginCompatibilityError, PluginContractError
from .models import PluginDescriptor


def validate_plugin(instance: object, descriptor: PluginDescriptor) -> Plugin:
    metadata = getattr(instance, "metadata", None)
    if not isinstance(metadata, PluginMetadata):
        raise PluginContractError("plugin metadata must be PluginMetadata")
    if type(metadata.protocol_version) is not int or metadata.protocol_version != PROTOCOL_VERSION:
        raise PluginCompatibilityError("incompatible plugin protocol")
    for name in ("plugin_id", "version", "protocol_version", "required_capabilities"):
        if getattr(metadata, name) != getattr(descriptor, name):
            raise PluginCompatibilityError("manifest and instance metadata differ: " + name)
    shapes: dict[str, tuple[tuple[object, ...], dict[str, object], bool]] = {
        "initialize": ((object(),), {}, True),
        "start": ((), {}, True),
        "stop": ((), {}, True),
        "close": ((), {}, True),
        "observe": ((), {}, True),
        "handle_command": ((object(),), {}, True),
        "parse_command": (("",), {"source": "cli"}, False),
        "format_state": ((object(),), {}, False),
    }
    for name, (args, kwargs, asynchronous) in shapes.items():
        method = getattr(instance, name, None)
        if not callable(method) or inspect.iscoroutinefunction(method) != asynchronous:
            raise PluginContractError("invalid plugin method convention: " + name)
        try:
            inspect.signature(method).bind(*args, **kwargs)
        except (ValueError, TypeError) as exc:
            raise PluginContractError("invalid plugin method signature: " + name) from exc
    return cast(Plugin, instance)


def validate_capabilities(metadata: PluginMetadata, providers: ProviderLookup) -> None:
    for name in metadata.required_capabilities:
        try:
            if name == "capture":
                providers.get(CaptureProvider)  # type: ignore[type-abstract]
            elif name == "input":
                providers.get(InputProvider)  # type: ignore[type-abstract]
            else:
                providers.get(name)
        except CapabilityUnavailableError as exc:
            # Preserve the exact public capability category and original cause.
            raise type(exc)(f"plugin {metadata.plugin_id}: capability {name}") from exc
