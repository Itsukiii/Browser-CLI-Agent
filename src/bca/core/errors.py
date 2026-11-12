"""Stable exception hierarchy for subsystem boundaries."""


class BCAError(Exception):
    """Base for BCA boundary and operational errors."""

    code = "bca.error"


class CapabilityUnavailableError(BCAError):
    code = "provider.unavailable"


class CapabilityNotFoundError(CapabilityUnavailableError):
    """Missing registration; preserves broad unavailable handlers."""

    code = "provider.not_found"


class CapabilityTypeError(CapabilityUnavailableError):
    code = "provider.type_mismatch"


class ValidationError(BCAError, ValueError):
    code = "protocol.invalid"


class SerializationError(ValidationError):
    code = "protocol.serialization"


class ProviderRegistrationError(BCAError):
    code = "provider.registration"


class ProviderError(BCAError):
    code = "provider.failure"


class PluginError(BCAError):
    code = "plugin.failure"


class CommandError(PluginError):
    code = "command.invalid"


class LifecycleError(BCAError):
    code = "lifecycle.invalid"
