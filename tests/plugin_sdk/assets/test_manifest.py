import json

import pytest

from bca.plugin_sdk.assets import AssetManifestError, AssetNotFoundError, AssetStore


def test_sorted_queries_and_no_decode(assets_root, manifest, monkeypatch):
    manifest(extras=[{"id": "a", "default_variant": "v", "variants": {"v": {"path": "rgb.png"}}}])
    from bca.plugin_sdk.assets import loader

    monkeypatch.setattr(loader, "decode", lambda *a, **k: pytest.fail("unexpected decode"))
    store = AssetStore(assets_root)
    assert store.ids() == ("a", "ui.confirm")
    assert store.variants("ui.confirm") == ("dialog.dark", "dialog.default", "toolbar.default")
    selection = store.resolve("ui.confirm")
    assert selection.variant_id == "dialog.default" and selection.scene == "dialog"
    assert selection.source == (assets_root / "rgb.png").resolve()
    assert store.cache_info().misses == 0
    with pytest.raises(AssetNotFoundError):
        store.variants("missing")


@pytest.mark.parametrize(
    "raw",
    [
        '{"schema_version":1,"schema_version":1,"assets":[]}',
        '{"schema_version":1,"assets":[],"x":NaN}',
        '{"schema_version":1,"assets":[],"x":1e999}',
        '{"schema_version":1,"assets":[],"x":Infinity}',
        '{"schema_version":true,"assets":[]}',
        '{"schema_version":2,"assets":[]}',
        '{"schema_version":1.0,"assets":[]}',
        '{"schema_version":1,"assets":{}}',
        "[]",
        "null",
        "{",
        '{"schema_version":1,"assets":[],"extra":1}',
    ],
)
def test_strict_json(assets_root, raw):
    (assets_root / "manifest.json").write_text(raw, encoding="utf-8")
    with pytest.raises(AssetManifestError):
        AssetStore(assets_root)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["assets"].append(d["assets"][0]),
        lambda d: d["assets"][0].update(id="UI.confirm"),
        lambda d: d["assets"][0].update(id="ui..confirm"),
        lambda d: d["assets"][0].update(default_variant="missing"),
        lambda d: d["assets"][0].update(variants={}),
        lambda d: d["assets"][0].update(extra=True),
        lambda d: d["assets"][0]["variants"].update({"Bad": {"path": "rgb.png"}}),
        lambda d: d["assets"][0]["variants"]["dialog.dark"].update(theme="Dark"),
        lambda d: d["assets"][0]["variants"]["dialog.dark"].update(scene=None),
        lambda d: d["assets"][0]["variants"]["dialog.dark"].update(extra=True),
        lambda d: d["assets"][0]["variants"]["dialog.dark"].update(size=[True, 1]),
        lambda d: d["assets"][0]["variants"]["dialog.dark"].update(size=[0, 1]),
        lambda d: d["assets"][0]["variants"]["dialog.dark"].update(size=[1.0, 1]),
        lambda d: d["assets"][0]["variants"]["dialog.dark"].update(size=[1]),
    ],
)
def test_invalid_structure(assets_root, manifest, mutation):
    doc = manifest()
    mutation(doc)
    (assets_root / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(AssetManifestError):
        AssetStore(assets_root)


def test_duplicate_nested_key_and_bad_utf8(assets_root):
    path = assets_root / "manifest.json"
    path.write_text('{"schema_version":1,"assets":[{"id":"a","id":"b"}]}')
    with pytest.raises(AssetManifestError, match="duplicate"):
        AssetStore(assets_root)
    path.write_bytes(b"\xff")
    with pytest.raises(AssetManifestError) as error:
        AssetStore(assets_root)
    assert isinstance(error.value.__cause__, UnicodeError)
