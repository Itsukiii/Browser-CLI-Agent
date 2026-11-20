"""Per-store LRU. The store lock serializes all access, including decoding."""

from collections import OrderedDict
from dataclasses import dataclass

from .models import AssetSelection, CacheInfo, LoadedTemplate
from .paths import FileIdentity


@dataclass(frozen=True, slots=True)
class CacheKey:
    selection: AssetSelection
    image: FileIdentity
    mask: FileIdentity | None


class TemplateCache:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.hits = self.misses = self.evictions = self.current_bytes = 0
        self.entries: OrderedDict[CacheKey, tuple[LoadedTemplate, int]] = OrderedDict()

    def get(self, key: CacheKey) -> LoadedTemplate | None:
        # Remove all contextual views of stale bytes, not only this scene selection.
        for old in tuple(self.entries):
            if (
                old.selection.asset_id == key.selection.asset_id
                and old.selection.variant_id == key.selection.variant_id
                and (old.image != key.image or old.mask != key.mask)
            ):
                self.remove(old)
        entry = self.entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        self.hits += 1
        self.entries.move_to_end(key)
        return entry[0]

    def remove(self, key: CacheKey) -> None:
        _, size = self.entries.pop(key)
        self.current_bytes -= size

    def put(self, key: CacheKey, value: LoadedTemplate) -> None:
        size = value.image.nbytes + (value.mask.nbytes if value.mask is not None else 0)
        if size > self.limit:
            return
        while self.current_bytes + size > self.limit:
            self.remove(next(iter(self.entries)))
            self.evictions += 1
        self.entries[key] = (value, size)
        self.current_bytes += size

    def invalidate(self, asset_id: str | None) -> None:
        for key in tuple(self.entries):
            if asset_id is None or key.selection.asset_id == asset_id:
                self.remove(key)

    def info(self) -> CacheInfo:
        return CacheInfo(
            hits=self.hits,
            misses=self.misses,
            evictions=self.evictions,
            entries=len(self.entries),
            current_bytes=self.current_bytes,
            limit_bytes=self.limit,
        )
