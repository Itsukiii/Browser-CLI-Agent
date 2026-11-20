from dataclasses import FrozenInstanceError

import pytest

from bca.plugin_sdk.assets import AssetProfile, AssetProfileError, AssetSelectionError, AssetStore


@pytest.mark.parametrize("override", ["", "[variants]\nui.confirm@dialog=dialog.dark\n"])
def test_documented_selection(assets_root, manifest, profile, override):
    path = profile("[profile]\nname=dark\ntheme=dark\ndefault_scene=dialog\n" + override)
    dark = AssetStore(assets_root, profile=path)
    light = AssetStore(assets_root)
    assert dark.resolve("ui.confirm").variant_id == "dialog.dark"
    toolbar = dark.resolve("ui.confirm", scene="toolbar")
    assert toolbar.variant_id == "toolbar.default" and toolbar.theme == "dark"
    assert dark.load("ui.confirm").image.tolist() == [[[1, 2, 3], [4, 5, 6]]]
    assert light.load("ui.confirm").image.tolist() == [[[10, 20, 30], [200, 100, 50]]]


def test_scene_override_precedes_asset_and_can_override_theme(assets_root, manifest, profile):
    store = AssetStore(
        assets_root,
        profile=profile(
            "[profile]\nname=dark\ntheme=dark\n[variants]\n"
            "ui.confirm=dialog.dark\nui.confirm@dialog=dialog.default\n"
        ),
    )
    selected = store.resolve("ui.confirm")
    assert selected.variant_id == "dialog.default" and selected.selected_by == "profile.scene"
    assert selected.theme == "dark" and selected.variant_theme == "default"
    with pytest.raises(AssetSelectionError):
        store.resolve("ui.confirm", scene="toolbar")


def test_specificity_default_tie_and_ambiguity(assets_root, manifest, profile):
    variants = {
        "fallback": {"path": "rgb.png"},
        "theme": {"path": "rgb.png", "theme": "dark"},
        "scene": {"path": "rgb.png", "scene": "dialog"},
    }
    manifest(variants, default="fallback")
    store = AssetStore(assets_root, profile=profile())
    assert store.resolve("ui.confirm").variant_id == "scene"  # scene outranks theme
    assert store.resolve("ui.confirm", scene="toolbar").variant_id == "theme"
    variants["scene_two"] = dict(variants["scene"])
    manifest(variants, default="fallback")
    with pytest.raises(AssetSelectionError, match="ambiguous"):
        AssetStore(assets_root, profile=profile()).resolve("ui.confirm")
    manifest(variants, default="scene_two")
    assert (
        AssetStore(assets_root, profile=profile()).resolve("ui.confirm").variant_id == "scene_two"
    )


def test_missing_dimensions_and_unavailable_scene(assets_root, manifest, profile):
    manifest(
        {"generic": {"path": "rgb.png"}, "specific": {"path": "dark.png", "scene": "dialog"}},
        default="generic",
    )
    assert AssetStore(assets_root).resolve("ui.confirm").variant_id == "generic"
    assert AssetStore(assets_root).resolve("ui.confirm", scene="dialog").variant_id == "specific"
    manifest()
    with pytest.raises(AssetSelectionError):
        AssetStore(assets_root).resolve("ui.confirm", scene="missing")
    with pytest.raises(AssetSelectionError):
        AssetStore(assets_root).resolve("ui.confirm", scene="Bad")
    with pytest.raises(AssetSelectionError):
        AssetStore(assets_root, profile=profile("[profile]\nname=x\ntheme=missing")).resolve(
            "ui.confirm"
        )


@pytest.mark.parametrize(
    "content",
    [
        "[profile]\nname=a\nname=b",
        "[profile]\nname=a\n[profile]\nname=a",
        "[other]\nname=a",
        "[profile]\nname=a\nunknown=x",
        "[profile]\ntheme=dark",
        "[profile]\nName=a",
        "[profile]\nname=Dark",
        "[profile]\nname=a\ntheme=%(x)s",
        "[DEFAULT]\nname=a\n[profile]",
        "[DEFAULT]\n[profile]\nname=a",
        "[profile]\nname=a\n[variants]\nui.confirm=missing",
        "[profile]\nname=a\n[variants]\nmissing=dialog.dark",
        "[profile]\nname=a\n[variants]\nui.confirm=",
        "[profile]\nname=a\n[variants]\nui.confirm@toolbar=dialog.dark",
        "[profile]\nname=a\n[variants]\nUI.confirm=dialog.dark",
        "[profile]\nname=a\n[variants]\nui.confirm@@dialog=dialog.dark",
        "[profile]\nname=a\n[variants]\nui.confirm=dialog.dark\nui.confirm=dialog.default",
    ],
)
def test_profile_rejects_invalid_configuration(assets_root, manifest, profile, content):
    with pytest.raises(AssetProfileError):
        AssetStore(assets_root, profile=profile(content))


def test_immutable_profile_snapshot(assets_root, manifest, profile):
    source = {"ui.confirm": "dialog.dark"}
    model = AssetProfile(overrides=source)
    source.clear()
    assert model.overrides["ui.confirm"] == "dialog.dark"
    store = AssetStore(assets_root, profile=profile())
    with pytest.raises(TypeError):
        store.profile.overrides["ui.confirm"] = "dialog.default"
    with pytest.raises(FrozenInstanceError):
        store.profile.theme = "light"
    with pytest.raises(AttributeError):
        store.profile = model
