import os
import shutil

import pytest
from PIL import Image

from bca.plugin_sdk.assets import AssetStore, AssetValidationError


def test_lru_counts_and_old_object_lifetime(assets_root, manifest):
    manifest(
        {
            "a": {"path": "rgb.png", "scene": "a"},
            "b": {"path": "dark.png", "scene": "b"},
            "c": {"path": "rgba.png", "scene": "c"},
        },
        default="a",
    )
    store = AssetStore(assets_root, cache_limit_bytes=14)
    a = store.load("ui.confirm", scene="a")  # 6 bytes
    b = store.load("ui.confirm", scene="b")  # 6 bytes
    assert store.load("ui.confirm", scene="a") is a
    c = store.load("ui.confirm", scene="c")  # 8 bytes, evicts b
    info = store.cache_info()
    assert (info.hits, info.misses, info.evictions, info.entries, info.current_bytes) == (
        1,
        3,
        1,
        2,
        14,
    )
    assert store.load("ui.confirm", scene="a") is a
    assert store.load("ui.confirm", scene="b") is not b
    assert b.image.tolist() == [[[1, 2, 3], [4, 5, 6]]]
    store.close()
    assert c.mask.tolist() == [[128, 255]]


@pytest.mark.parametrize("limit", [0, 5])
def test_disabled_or_oversized(assets_root, manifest, limit):
    store = AssetStore(assets_root, cache_limit_bytes=limit)
    assert store.load("ui.confirm") is not store.load("ui.confirm")
    assert store.cache_info().entries == store.cache_info().current_bytes == 0
    assert store.cache_info().misses == 2 and store.cache_info().evictions == 0


@pytest.mark.parametrize("limit", [True, -1, 1.5, "64"])
def test_bad_budget(assets_root, limit):
    with pytest.raises(AssetValidationError):
        AssetStore(assets_root, cache_limit_bytes=limit)


def test_file_mask_identity_and_explicit_invalidation(assets_root, manifest, monkeypatch):
    manifest({"v": {"path": "rgb.png", "mask": "mask.png"}}, default="v")
    store = AssetStore(assets_root)
    first = store.load("ui.confirm")
    for filename, mode, color in (("rgb.png", "RGB", (7, 8, 9)), ("mask.png", "L", 200)):
        path = assets_root / filename
        before = path.stat()
        with Image.new(mode, (2, 1), color) as image:
            image.save(path)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        new = store.load("ui.confirm")
        assert new is not first
        first = new
        assert store.cache_info().entries == 1
    assert first.image.tolist() == [[[7, 8, 9], [7, 8, 9]]]
    assert first.mask.tolist() == [[200, 200]]
    store.invalidate("ui.confirm")
    assert store.load("ui.confirm") is not first
    store.clear_cache()
    assert store.cache_info().current_bytes == 0
    assert store.cache_info().evictions == 0  # only budget removals count as evictions


def test_root_isolation_and_id_scoped_invalidate(assets_root, manifest):
    manifest(
        extras=[{"id": "other", "default_variant": "v", "variants": {"v": {"path": "rgb.png"}}}]
    )
    other_root = assets_root / "second"
    shutil.copytree(assets_root, other_root, ignore=shutil.ignore_patterns("second"))
    one, two = AssetStore(assets_root), AssetStore(other_root)
    first = one.load("ui.confirm")
    assert two.load("ui.confirm") is not first
    other = one.load("other")
    one.invalidate("ui.confirm")
    assert one.load("other") is other
    assert one.load("ui.confirm") is not first
    assert two.cache_info().misses == 1
    one.invalidate()
    assert one.cache_info().entries == 0 and two.cache_info().entries == 1
