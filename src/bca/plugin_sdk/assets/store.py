"""Synchronous, independently owned asset catalog/profile/cache lifetime."""

from pathlib import Path
from threading import RLock

from .cache import CacheKey, TemplateCache
from .errors import AssetClosedError, AssetNotFoundError, AssetPathError, AssetValidationError
from .loader import load_template
from .manifest import Asset, parse_manifest
from .models import AssetProfile, AssetSelection, CacheInfo, LoadedTemplate
from .paths import inspect_file, read_file, relative_path, root_directory
from .profile import choose, parse_profile


class AssetStore:
    def __init__(
        self,
        root: Path,
        *,
        manifest: str = "manifest.json",
        profile: Path | None = None,
        cache_limit_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        if not isinstance(root, Path) or (profile is not None and not isinstance(profile, Path)):
            raise AssetPathError("root/profile: expected Path")
        if type(cache_limit_bytes) is not int or cache_limit_bytes < 0:
            raise AssetValidationError("cache_limit_bytes: expected nonnegative integer")
        self._lock = RLock()
        self._closed = False
        self._root = root_directory(root)
        self._manifest = self._root / relative_path(manifest)
        self._assets = parse_manifest(self._root, self._manifest)
        profile_path = None
        if profile is not None:
            profile_path = (
                profile if profile.is_absolute() else self._root / relative_path(profile.as_posix())
            )
        self._profile = parse_profile(self._root, profile_path, self._assets)
        self._cache = TemplateCache(cache_limit_bytes)

    def _open(self) -> None:
        if self._closed:
            raise AssetClosedError("store: closed")

    def _asset(self, asset_id: str) -> Asset:
        if not isinstance(asset_id, str) or asset_id not in self._assets:
            raise AssetNotFoundError("asset: unknown semantic id")
        return self._assets[asset_id]

    @property
    def profile(self) -> AssetProfile:
        with self._lock:
            self._open()
            return self._profile

    def ids(self) -> tuple[str, ...]:
        with self._lock:
            self._open()
            return tuple(sorted(self._assets))

    def variants(self, asset_id: str) -> tuple[str, ...]:
        with self._lock:
            self._open()
            return tuple(sorted(self._asset(asset_id).variants))

    def resolve(self, asset_id: str, *, scene: str | None = None) -> AssetSelection:
        with self._lock:
            self._open()
            name, variant, effective, reason = choose(
                asset_id, self._asset(asset_id), self._profile, scene
            )
            source = inspect_file(self._root, self._root / variant.path).path
            mask = (
                inspect_file(self._root, self._root / variant.mask).path if variant.mask else None
            )
            return AssetSelection(
                asset_id=asset_id,
                variant_id=name,
                scene=effective,
                theme=self._profile.theme,
                source=source,
                mask_source=mask,
                size=variant.size,
                variant_scene=variant.scene,
                variant_theme=variant.theme,
                selected_by=reason,
                manifest_source=self._manifest.resolve(),
                profile_source=self._profile.source,
            )

    def load(self, asset_id: str, *, scene: str | None = None) -> LoadedTemplate:
        with self._lock:
            self._open()
            self._asset(asset_id)
            try:
                return self._load(asset_id, scene=scene)
            except AssetPathError:
                # A removed/retargeted file must not leave stale cached references.
                self._cache.invalidate(asset_id)
                raise

    def _load(self, asset_id: str, *, scene: str | None) -> LoadedTemplate:
        with self._lock:
            selection = self.resolve(asset_id, scene=scene)
            variant = self._asset(asset_id).variants[selection.variant_id]
            # Retain lexical paths so retargeted links are checked again after decoding.
            image_path = self._root / variant.path
            mask_path = self._root / variant.mask if variant.mask else None
            image_id = inspect_file(self._root, image_path)
            mask_id = inspect_file(self._root, mask_path) if mask_path else None
            if (
                image_id.path != selection.source
                or (mask_id.path if mask_id else None) != selection.mask_source
            ):
                raise AssetPathError("resource: path changed during selection")
            key = CacheKey(selection, image_id, mask_id)
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            try:
                pixels = read_file(self._root, image_path, image_id)
                mask = read_file(self._root, mask_path, mask_id) if mask_path else None
                loaded = load_template(selection, pixels, mask)
                if inspect_file(self._root, image_path) != image_id or (
                    mask_path and inspect_file(self._root, mask_path) != mask_id
                ):
                    raise AssetPathError("resource: changed during decode")
            except BaseException:
                self._cache.invalidate(asset_id)
                raise
            self._cache.put(key, loaded)
            return loaded

    def invalidate(self, asset_id: str | None = None) -> None:
        with self._lock:
            self._open()
            if asset_id is not None:
                self._asset(asset_id)
            self._cache.invalidate(asset_id)

    def clear_cache(self) -> None:
        self.invalidate()

    def cache_info(self) -> CacheInfo:
        with self._lock:
            self._open()
            return self._cache.info()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._cache.invalidate(None)
                self._assets = {}
