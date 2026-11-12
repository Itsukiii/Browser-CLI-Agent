"""Plugin contracts; no dependency on the optional SDK or concrete plugins."""

from dataclasses import dataclass, field
from logging import Logger
from typing import Protocol

from bca.core.errors import ValidationError
from bca.core.protocol import Action, Command, JsonObject, Model, PageState
from bca.core.protocol.validation import json_object, token
from bca.core.providers import ProviderLookup
from bca.core.runtime import EventSink, StateSink


@dataclass(frozen=True, kw_only=True)
class PluginMetadata(Model):
    plugin_id: str
    version: str
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        token(self.plugin_id, "plugin_id")
        token(self.version, "version")
        if not isinstance(self.required_capabilities, tuple):
            raise ValidationError("required_capabilities must be a tuple")
        for capability in self.required_capabilities:
            token(capability, "capability")
        if len(set(self.required_capabilities)) != len(self.required_capabilities):
            raise ValidationError("duplicate required capabilities")


@dataclass(frozen=True, kw_only=True)
class PluginConfig(Model):
    values: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        json_object(self.values, "values")


@dataclass(frozen=True, slots=True)
class PluginContext:
    providers: ProviderLookup
    states: StateSink
    events: EventSink
    logger: Logger
    config: PluginConfig


class Plugin(Protocol):
    @property
    def metadata(self) -> PluginMetadata: ...

    async def initialize(self, context: PluginContext) -> None: ...

    async def start(self) -> None: ...

    async def observe(self) -> PageState:
        """Acquire and interpret page information; runtime publishes the returned state."""
        ...

    def parse_command(self, text: str, *, source: str = "cli") -> Command: ...

    async def handle_command(self, command: Command) -> tuple[Action, ...]:
        """Map a command to ordered actions. Core owns their execution."""
        ...

    def format_state(self, state: PageState) -> str: ...

    async def stop(self) -> None: ...

    async def close(self) -> None: ...


__all__ = ["Plugin", "PluginConfig", "PluginContext", "PluginMetadata"]
