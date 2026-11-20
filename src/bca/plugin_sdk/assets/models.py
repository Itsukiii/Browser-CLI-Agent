"""SDK-local immutable snapshots, independent of Protocol serialization."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, kw_only=True, slots=True)
class AssetProfile:
    name: str = "default"
    theme: str | None = None
    default_scene: str | None = None
    overrides: Mapping[str, str] = field(default_factory=dict)
    source: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "overrides", MappingProxyType(dict(self.overrides)))


@dataclass(frozen=True, kw_only=True, slots=True)
class AssetSelection:
    asset_id: str
    variant_id: str
    scene: str | None
    theme: str | None
    source: Path
    mask_source: Path | None
    size: tuple[int, int] | None
    variant_scene: str | None
    variant_theme: str | None
    selected_by: str
    manifest_source: Path
    profile_source: Path | None


@dataclass(frozen=True, kw_only=True, slots=True, eq=False)
class LoadedTemplate:
    asset_id: str
    variant_id: str
    image: NDArray[np.uint8]
    mask: NDArray[np.uint8] | None
    width: int
    height: int
    source: Path
    selection: AssetSelection


@dataclass(frozen=True, kw_only=True, slots=True)
class CacheInfo:
    hits: int
    misses: int
    evictions: int
    entries: int
    current_bytes: int
    limit_bytes: int
