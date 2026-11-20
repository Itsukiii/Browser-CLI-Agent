"""Optional asset SDK. Install browser-cli-agent[assets] to use NumPy templates."""

from .errors import (
    AssetClosedError,
    AssetDecodeError,
    AssetError,
    AssetManifestError,
    AssetNotFoundError,
    AssetPathError,
    AssetProfileError,
    AssetSelectionError,
    AssetValidationError,
)
from .models import AssetProfile, AssetSelection, CacheInfo, LoadedTemplate
from .store import AssetStore

__all__ = [
    "AssetStore",
    "AssetProfile",
    "AssetSelection",
    "LoadedTemplate",
    "CacheInfo",
    "AssetError",
    "AssetManifestError",
    "AssetProfileError",
    "AssetNotFoundError",
    "AssetSelectionError",
    "AssetPathError",
    "AssetDecodeError",
    "AssetValidationError",
    "AssetClosedError",
]
