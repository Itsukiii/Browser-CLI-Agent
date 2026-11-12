import asyncio

import pytest

from bca.core.errors import (
    BCAError,
    CapabilityUnavailableError,
    ProviderError,
    ProviderRegistrationError,
)
from bca.core.providers import CaptureProvider, InputProvider, Provider, ProviderRegistry


class FakeCapture(CaptureProvider):
    def __init__(self, frame):
        self.frame = frame
        self.ready = False

    @property
    def available(self):
        return self.ready

    async def start(self):
        self.ready = True

    async def close(self):
        self.ready = False

    async def capture(self, page_id):
        if not self.available or page_id != self.frame.page_id:
            raise ProviderError("page unavailable")
        return self.frame


def test_abstract_contract():
    for cls in (Provider, CaptureProvider, InputProvider):
        with pytest.raises(TypeError):
            cls()


def test_registry_and_lifecycle(frame):
    async def scenario():
        registry = ProviderRegistry()
        provider = FakeCapture(frame)
        registry.register(provider)
        assert registry.capabilities == ("capture",)
        assert not registry.available("capture")
        with pytest.raises(CapabilityUnavailableError):
            registry.get(CaptureProvider)
        await provider.start()
        await provider.start()
        assert registry.get("capture") is registry.get(CaptureProvider)
        assert await registry.get(CaptureProvider).capture("demo") is frame
        with pytest.raises(ProviderError):
            await provider.capture("missing")
        with pytest.raises(ProviderRegistrationError):
            registry.register(provider)
        assert not registry.available(InputProvider)
        assert not registry.available("dom")
        await provider.close()
        await provider.close()
        assert not registry.available(CaptureProvider)

    asyncio.run(scenario())


def test_extensibility_and_type_mismatch(frame):
    class DomProvider(FakeCapture):
        capability = "dom"

    class Impostor(FakeCapture):
        capability = "input"

    registry = ProviderRegistry()
    dom = DomProvider(frame)
    dom.ready = True
    registry.register(dom)
    assert registry.get(DomProvider) is dom
    registry.register(Impostor(frame))
    with pytest.raises(CapabilityUnavailableError, match="type mismatch"):
        registry.get(InputProvider)
    with pytest.raises(ProviderRegistrationError):
        registry.register(object())
    dom.capability = "bad name"
    with pytest.raises(ProviderRegistrationError):
        ProviderRegistry().register(dom)
    assert issubclass(ProviderRegistrationError, BCAError)
    assert ProviderError.code == "provider.failure"
