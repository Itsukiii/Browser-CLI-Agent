import json
from pathlib import Path

import pytest

from bca.plugin_sdk.assets import AssetPathError, AssetStore


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/absolute.png",
        "C:/x.png",
        "C:x.png",
        "../rgb.png",
        "a/../rgb.png",
        "./rgb.png",
        "a//b.png",
        "a\\b.png",
        "a\x00b.png",
        "a:b.png",
        "a?.png",
        "a*.png",
        "a|b.png",
        "a<b.png",
        'a"b.png',
        "NUL.png",
        "a./x.png",
        "a /x.png",
    ],
)
def test_invalid_manifest_paths(assets_root, manifest, path):
    manifest({"v": {"path": path}}, default="v")
    with pytest.raises(AssetPathError):
        AssetStore(assets_root)


@pytest.mark.parametrize("field", ["path", "mask"])
def test_missing_directory_or_unreadable(assets_root, manifest, monkeypatch, field):
    for path in ("missing.png", "directory"):
        (assets_root / "directory").mkdir(exist_ok=True)
        manifest({"v": {"path": "rgb.png", field: path}}, default="v")
        with pytest.raises(AssetPathError):
            AssetStore(assets_root)
    manifest({"v": {"path": "rgb.png", field: "mask.png"}}, default="v")
    store = AssetStore(assets_root)
    original = Path.open

    def denied(self, *args, **kwargs):
        if self.name == "mask.png":
            raise PermissionError("do not expose this secret")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(AssetPathError) as error:
        store.load("ui.confirm")
    assert isinstance(error.value.__cause__, PermissionError)
    assert "secret" not in str(error.value)
    assert store.cache_info().entries == 0


def test_all_files_confined_and_rechecked(assets_root, manifest, profile, monkeypatch, tmp_path):
    outside = assets_root.parent / (assets_root.name + "-outside.png")
    outside.write_bytes((assets_root / "rgb.png").read_bytes())
    manifest()
    store = AssetStore(assets_root)
    original = Path.resolve

    def escaped(self, *args, **kwargs):
        if self.name == "rgb.png":
            return outside
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", escaped)
    with pytest.raises(AssetPathError, match="outside"):
        store.load("ui.confirm")
    with pytest.raises(AssetPathError):
        AssetStore(assets_root)


def test_real_symlink_or_documented_windows_limit(assets_root, manifest):
    outside = assets_root.parent / (assets_root.name + "-external.png")
    outside.write_bytes((assets_root / "rgb.png").read_bytes())
    link = assets_root / "link.png"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        assert getattr(exc, "winerror", None) == 1314
        result = {"status": "not_verified", "winerror": 1314}
    else:
        manifest({"v": {"path": "link.png"}}, default="v")
        with pytest.raises(AssetPathError):
            AssetStore(assets_root)
        result = {"status": "passed"}
    (assets_root / "symlink-result.json").write_text(json.dumps(result), encoding="utf-8")


def test_root_manifest_profile_and_foreign_cwd(assets_root, manifest, profile, monkeypatch):
    path = profile()
    monkeypatch.chdir(assets_root.parent)
    store = AssetStore(assets_root, profile=assets_root / path)
    assert store.load("ui.confirm").variant_id == "dialog.dark"
    for kwargs in (
        {"manifest": "../manifest.json"},
        {"profile": Path("../profile.ini")},
        {"profile": assets_root.parent / "no-profile.ini"},
    ):
        with pytest.raises(AssetPathError):
            AssetStore(assets_root, **kwargs)
    for root in (assets_root / "missing", assets_root / "rgb.png"):
        with pytest.raises(AssetPathError):
            AssetStore(root)


def test_mutation_during_read_or_decode_not_cached(assets_root, manifest, monkeypatch):
    from bca.plugin_sdk.assets import paths
    from bca.plugin_sdk.assets import store as module

    manifest()
    value = AssetStore(assets_root)
    original = module.load_template

    def changed(*args):
        result = original(*args)
        with (assets_root / "rgb.png").open("ab") as stream:
            stream.write(b"changed")
        return result

    monkeypatch.setattr(module, "load_template", changed)
    with pytest.raises(AssetPathError, match="changed during decode"):
        value.load("ui.confirm")
    assert value.cache_info().entries == 0
    ident = paths.inspect_file(assets_root, assets_root / "rgb.png")
    (assets_root / "rgb.png").write_bytes(b"new")
    with pytest.raises(AssetPathError, match="before read"):
        paths.read_file(assets_root, assets_root / "rgb.png", ident)
