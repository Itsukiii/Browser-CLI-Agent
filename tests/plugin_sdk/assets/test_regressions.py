import json
import os
import struct
import zlib
from pathlib import Path

import pytest
from PIL import Image

from bca.plugin_sdk.assets import (
    AssetPathError,
    AssetProfileError,
    AssetStore,
    AssetValidationError,
)


def test_windows_path_and_descriptor_identity_agree(assets_root):
    from bca.plugin_sdk.assets.paths import identity, read_file

    path = assets_root / "rgb.png"
    before = identity(path, path.stat())
    with path.open("rb") as stream:
        assert identity(path, os.fstat(stream.fileno())) == before
    assert read_file(assets_root, path, before) == path.read_bytes()


def test_same_metadata_edit_requires_explicit_invalidation(assets_root, manifest):
    path = assets_root / "rgb.png"
    with Image.new("RGB", (2, 1), (1, 2, 3)) as image:
        image.save(path, compress_level=0)
    store = AssetStore(assets_root)
    first = store.load("ui.confirm")
    before = path.stat()
    with Image.new("RGB", (2, 1), (4, 5, 6)) as image:
        image.save(path, compress_level=0)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    assert store.load("ui.confirm") is first
    store.invalidate()
    assert store.load("ui.confirm").image.tolist() == [[[4, 5, 6], [4, 5, 6]]]


def test_removed_file_drops_cached_references(assets_root, manifest):
    store = AssetStore(assets_root)
    first = store.load("ui.confirm")
    (assets_root / "rgb.png").unlink()
    with pytest.raises(AssetPathError):
        store.load("ui.confirm")
    assert store.cache_info().entries == store.cache_info().current_bytes == 0
    assert first.image[0, 0].tolist() == [10, 20, 30]


@pytest.mark.parametrize("resource", ["manifest.json", "profile.ini", "mask.png"])
def test_boundary_applies_to_each_resource(assets_root, manifest, profile, monkeypatch, resource):
    manifest({"v": {"path": "rgb.png", "mask": "mask.png"}}, default="v")
    profile_path = profile("[profile]\nname=test")
    outside = assets_root.parent / (assets_root.name + "-outside")
    outside.write_bytes((assets_root / resource).read_bytes())
    original = Path.resolve

    def redirect(self, *args, **kwargs):
        if self == assets_root / resource:
            return outside
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", redirect)
    with pytest.raises(AssetPathError, match="outside"):
        AssetStore(assets_root, profile=profile_path)


def test_legal_internal_subdirectory_and_absolute_profile(assets_root, manifest):
    sub = assets_root / "templates"
    sub.mkdir()
    (sub / "rgb.png").write_bytes((assets_root / "rgb.png").read_bytes())
    (sub / "profile.ini").write_text("[profile]\nname=local", encoding="utf-8")
    manifest({"v": {"path": "templates/rgb.png"}}, default="v")
    store = AssetStore(assets_root, profile=sub / "profile.ini")
    assert store.load("ui.confirm").source == (sub / "rgb.png").resolve()


def test_actual_large_dimensions_rejected_without_allocating(assets_root, manifest):
    data = bytearray((assets_root / "rgb.png").read_bytes())
    data[16:24] = struct.pack(">II", 4097, 4096)  # exceeds 16,777,216 pixels
    data[29:33] = struct.pack(">I", zlib.crc32(data[12:29]))
    (assets_root / "large.png").write_bytes(data)
    manifest({"v": {"path": "large.png"}}, default="v")
    with pytest.raises(AssetValidationError, match="pixel limit"):
        AssetStore(assets_root).load("ui.confirm")


def test_encoded_size_limit(assets_root, manifest, monkeypatch):
    from bca.plugin_sdk.assets import paths

    store = AssetStore(assets_root)
    monkeypatch.setattr(paths, "MAX_FILE_BYTES", 1)
    with pytest.raises(AssetPathError, match="limit"):
        store.load("ui.confirm")


def test_file_changes_between_open_and_read_are_rejected(assets_root, monkeypatch):
    from bca.plugin_sdk.assets import paths

    original = paths.os.fstat
    calls = 0

    def changed(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            with (assets_root / "rgb.png").open("ab") as stream:
                stream.write(b"changed")
        return original(descriptor)

    monkeypatch.setattr(paths.os, "fstat", changed)
    with pytest.raises(AssetPathError, match="during read"):
        paths.read_file(assets_root, assets_root / "rgb.png")


def test_selection_order_is_not_json_order(assets_root, manifest, profile):
    variants = {
        "fallback": {"path": "rgb.png"},
        "dark": {"path": "dark.png", "scene": "dialog", "theme": "dark"},
        "scene": {"path": "rgb.png", "scene": "dialog"},
    }
    for ordered in (variants, dict(reversed(list(variants.items())))):
        manifest(ordered, default="fallback")
        assert AssetStore(assets_root, profile=profile()).resolve("ui.confirm").variant_id == "dark"


def test_profile_invalid_utf8_and_source_snapshot(assets_root, manifest, profile):
    path = profile()
    store = AssetStore(assets_root, profile=path)
    (assets_root / path).write_bytes(b"\xff")
    assert store.profile.theme == "dark"  # constructor snapshot, no implicit hot reload
    with pytest.raises(AssetProfileError):
        AssetStore(assets_root, profile=path)


def test_generic_variant_context_is_not_misattributed_on_hit(assets_root, manifest):
    manifest({"generic": {"path": "rgb.png"}}, default="generic")
    store = AssetStore(assets_root)
    one = store.load("ui.confirm", scene="dialog")
    two = store.load("ui.confirm", scene="toolbar")
    assert one.selection.scene == "dialog" and two.selection.scene == "toolbar"
    assert store.load("ui.confirm", scene="toolbar") is two
    assert store.cache_info().current_bytes == 12


def test_id_invalidation_removes_all_variant_views(assets_root, manifest):
    store = AssetStore(assets_root)
    store.load("ui.confirm")
    store.load("ui.confirm", scene="toolbar")
    assert store.cache_info().entries == 2
    store.invalidate("ui.confirm")
    assert store.cache_info().entries == 0


def test_metadata_empty_catalog_and_default_budget(assets_root):
    (assets_root / "manifest.json").write_text(json.dumps({"schema_version": 1, "assets": []}))
    store = AssetStore(assets_root)
    assert store.ids() == () and store.profile.name == "default"
    assert store.cache_info().limit_bytes == 64 * 1024 * 1024
