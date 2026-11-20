"""Read-only lookup with non-owning capability overrides."""

from collections.abc import Mapping
from typing import TypeVar, overload

from bca.core.errors import CapabilityTypeError, CapabilityUnavailableError, ValidationError
from bca.core.protocol.validation import token
from bca.core.providers import Provider, ProviderLookup

P = TypeVar("P", bound=Provider)


class ProviderLookupView:
    def __init__(
        self, base: ProviderLookup, *, overrides: Mapping[str, Provider] | None = None
    ) -> None:
        self._base = base
        self._overrides = dict(overrides or {})
        for name, provider in self._overrides.items():
            token(name, "capability")
            if not isinstance(provider, Provider) or provider.capability != name:
                raise ValidationError("override capability must match Provider")

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
        if name not in self._overrides:
            return self._base.get(capability)
        provider = self._overrides[name]
        if not isinstance(capability, str) and not isinstance(provider, capability):
            raise CapabilityTypeError("override capability type mismatch")
        if not provider.available:
            raise CapabilityUnavailableError("override capability is not ready")
        return provider

    def available(self, capability: str | type[Provider]) -> bool:
        try:
            self.get(capability)
        except CapabilityUnavailableError:
            return False
        return True
