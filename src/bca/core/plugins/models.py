"""Frozen plugin catalog and lifecycle diagnostics (not Protocol codec models)."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


@dataclass(frozen=True, kw_only=True)
class PluginDescriptor:
    plugin_id: str
    version: str
    protocol_version: int
    required_capabilities: tuple[str, ...]
    directory: Path
    factory: str = "create_plugin"


@dataclass(frozen=True, kw_only=True)
class PluginDiscoveryIssue:
    source: Path
    error_type: str
    message: str
    plugin_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class CatalogSnapshot:
    candidates: tuple[PluginDescriptor, ...] = ()
    issues: tuple[PluginDiscoveryIssue, ...] = ()


class PluginLifecycleState(StrEnum):
    CREATED = "created"
    LOADED = "loaded"
    INITIALIZING = "initializing"
    INITIALIZED = "initialized"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


@dataclass(frozen=True, kw_only=True)
class PluginSnapshot:
    plugin_id: str | None
    version: str | None
    state: PluginLifecycleState
    required_capabilities: tuple[str, ...] = ()
    last_error: str | None = None
    cleanup_status: str = "not_started"
    cleanup_error: str | None = None
