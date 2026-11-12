"""Capability lookup without browser implementation dependencies."""

from typing import Protocol, TypeVar, overload

from bca.core.errors import (
    CapabilityNotFoundError,
    CapabilityTypeError,
    CapabilityUnavailableError,
    ProviderRegistrationError,
    ValidationError,
)
from bca.core.protocol.validation import token

from .base import Provider

P = TypeVar("P", bound=Provider)


class ProviderLookup(Protocol):
    """Read-only capability port injected into plugins by Runtime."""

    @overload
    def get(self, capability: str) -> Provider: ...

    @overload
    def get(self, capability: type[P]) -> P: ...

    def available(self, capability: str | type[Provider]) -> bool: ...


class ProviderRegistry:
    """One implementation per capability; registration does not start or close it."""

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        if not isinstance(provider, Provider):
            raise ProviderRegistrationError("provider must implement Provider")
        name = getattr(provider, "capability", None)
        if not isinstance(name, str) or not name or any(c.isspace() for c in name):
            raise ProviderRegistrationError("capability must be a nonempty token")
        if name in self._providers:
            raise ProviderRegistrationError(f"duplicate capability: {name}")
        self._providers[name] = provider

    @overload
    def get(self, capability: str) -> Provider: ...

    @overload
    def get(self, capability: type[P]) -> P: ...

    def get(self, capability: str | type[P]) -> Provider:
        if isinstance(capability, str):
            token(capability, "capability")
            name = capability
        elif isinstance(capability, type) and issubclass(capability, Provider):
            name = getattr(capability, "capability", "")
        else:
            raise ValidationError("expected capability name or Provider subclass")
        provider = self._providers.get(name)
        if provider is None:
            raise CapabilityNotFoundError(f"capability is not registered: {name}")
        if not isinstance(capability, str) and not isinstance(provider, capability):
            raise CapabilityTypeError(f"capability type mismatch: {name}")
        if not provider.available:
            raise CapabilityUnavailableError(f"capability is not ready: {name}")
        return provider

    def available(self, capability: str | type[Provider]) -> bool:
        try:
            self.get(capability)
        except CapabilityUnavailableError:
            return False
        return True

    @property
    def capabilities(self) -> tuple[str, ...]:
        """Registered names, including providers that are currently unavailable."""
        return tuple(self._providers)
