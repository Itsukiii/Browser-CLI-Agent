"""Deterministic metadata-only discovery under explicit trusted local roots."""

import keyword
import tomllib
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from bca.core.errors import ValidationError
from bca.core.protocol import PROTOCOL_VERSION
from bca.core.protocol.validation import token

from .errors import PluginCompatibilityError, PluginDuplicateIdError, PluginManifestError
from .models import CatalogSnapshot, PluginDescriptor, PluginDiscoveryIssue


def read_descriptor(directory: Path, root: Path) -> PluginDescriptor:
    directory = directory.resolve(strict=True)
    if not directory.is_relative_to(root):
        raise PluginManifestError("plugin directory escapes configured root")
    for name in ("plugin.toml", "__init__.py"):
        path = (directory / name).resolve(strict=True)
        if not path.is_relative_to(directory) or not path.is_file():
            raise PluginManifestError("plugin file escapes its directory or is not a file")
    with (directory / "plugin.toml").open("rb") as stream:
        document = tomllib.load(stream)
    values = document.get("plugin")
    if (
        set(document) != {"plugin"}
        or not isinstance(values, dict)
        or set(values)
        - {"plugin_id", "version", "protocol_version", "required_capabilities", "factory"}
    ):
        raise PluginManifestError("invalid manifest fields")
    plugin_id, version = values.get("plugin_id"), values.get("version")
    token(plugin_id, "plugin_id")
    token(version, "version")
    assert isinstance(plugin_id, str) and isinstance(version, str)
    protocol = values.get("protocol_version")
    if type(protocol) is not int or protocol != PROTOCOL_VERSION:
        raise PluginCompatibilityError("incompatible manifest protocol")
    capabilities = values.get("required_capabilities")
    if not isinstance(capabilities, list):
        raise PluginManifestError("required_capabilities must be an array")
    for name in capabilities:
        token(name, "capability")
    if len(set(capabilities)) != len(capabilities):
        raise PluginManifestError("duplicate required capabilities")
    factory = values.get("factory", "create_plugin")
    if not isinstance(factory, str) or not factory.isidentifier() or keyword.iskeyword(factory):
        raise PluginManifestError("factory must be an identifier")
    return PluginDescriptor(
        plugin_id=plugin_id,
        version=version,
        protocol_version=protocol,
        required_capabilities=tuple(capabilities),
        directory=directory,
        factory=factory,
    )


class PluginCatalog:
    def __init__(self, roots: Sequence[Path]) -> None:
        if isinstance(roots, (str, bytes)) or any(not isinstance(p, Path) for p in roots):
            raise ValidationError("roots must be Paths")
        self._roots = tuple(sorted({p.resolve() for p in roots}, key=lambda p: str(p).casefold()))
        self._snapshot = CatalogSnapshot()

    def discover(self) -> CatalogSnapshot:
        candidates: list[PluginDescriptor] = []
        issues: list[PluginDiscoveryIssue] = []
        seen: set[Path] = set()
        for root in self._roots:
            try:
                children = sorted(root.iterdir(), key=lambda p: str(p).casefold())
            except OSError as exc:
                issues.append(
                    PluginDiscoveryIssue(
                        source=root,
                        error_type=type(exc).__name__,
                        message="cannot scan configured root",
                    )
                )
                continue
            for child in children:
                if child.name == "__pycache__":
                    continue
                try:
                    if not child.is_dir():
                        continue
                    resolved = child.resolve(strict=True)
                    if resolved in seen:
                        continue
                    descriptor = read_descriptor(child, root)
                    seen.add(resolved)
                    candidates.append(descriptor)
                except (OSError, ValueError, PluginManifestError, PluginCompatibilityError) as exc:
                    issues.append(
                        PluginDiscoveryIssue(
                            source=child,
                            error_type=type(exc).__name__,
                            message="invalid plugin candidate",
                        )
                    )
        counts = Counter(d.plugin_id for d in candidates)
        for descriptor in candidates:
            if counts[descriptor.plugin_id] > 1:
                issues.append(
                    PluginDiscoveryIssue(
                        source=descriptor.directory,
                        error_type="PluginDuplicateIdError",
                        message="conflicting plugin ID",
                        plugin_id=descriptor.plugin_id,
                    )
                )
        self._snapshot = CatalogSnapshot(
            candidates=tuple(d for d in candidates if counts[d.plugin_id] == 1),
            issues=tuple(issues),
        )
        return self._snapshot

    def get(self, plugin_id: str) -> PluginDescriptor:
        token(plugin_id, "plugin_id")
        for descriptor in self._snapshot.candidates:
            if descriptor.plugin_id == plugin_id:
                return descriptor
        if any(i.plugin_id == plugin_id for i in self._snapshot.issues):
            raise PluginDuplicateIdError("plugin ID has conflicting sources")
        raise PluginManifestError("plugin ID is not in the discovered catalog")
