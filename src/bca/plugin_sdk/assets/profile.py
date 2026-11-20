"""INI v1 validation and deterministic scene/theme selection."""

import configparser
import re
from collections.abc import Mapping
from pathlib import Path

from .errors import AssetProfileError, AssetSelectionError
from .manifest import Asset, Variant, token
from .models import AssetProfile
from .paths import inspect_file, read_file


class StrictParser(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def parse_profile(root: Path, path: Path | None, assets: Mapping[str, Asset]) -> AssetProfile:
    if path is None:
        return AssetProfile()
    source = inspect_file(root, path).path
    parser = StrictParser(interpolation=None, strict=True)
    try:
        content = read_file(root, path).decode("utf-8")
        if re.search(r"^\s*\[DEFAULT\]", content, re.MULTILINE):
            raise AssetProfileError("profile: DEFAULT section not allowed")
        parser.read_string(content)
    except (configparser.Error, UnicodeError) as exc:
        raise AssetProfileError("profile: invalid UTF-8 INI") from exc
    if parser.defaults() or parser.has_section("DEFAULT"):
        raise AssetProfileError("profile: DEFAULT values not allowed")
    if "profile" not in parser or set(parser.sections()) - {"profile", "variants"}:
        raise AssetProfileError("profile: missing or unknown section")
    values = dict(parser["profile"])
    if "name" not in values or values.keys() - {"name", "theme", "default_scene"}:
        raise AssetProfileError("profile: missing or unknown field")
    if any(not token(value, dotted=False) for value in values.values()):
        raise AssetProfileError("profile: invalid lowercase identifier")
    overrides = dict(parser["variants"]) if "variants" in parser else {}
    for key, name in overrides.items():
        parts = key.split("@")
        if (
            len(parts) > 2
            or not token(parts[0])
            or (len(parts) == 2 and not token(parts[1], dotted=False))
            or not token(name)
        ):
            raise AssetProfileError("variants: invalid override identifier")
        asset = assets.get(parts[0])
        if asset is None or name not in asset.variants:
            raise AssetProfileError("variants: unknown asset or variant reference")
        if len(parts) == 2 and asset.variants[name].scene not in (None, parts[1]):
            raise AssetProfileError("variants: scene-specific override conflicts with variant")
    return AssetProfile(
        name=values["name"],
        theme=values.get("theme"),
        default_scene=values.get("default_scene"),
        overrides=overrides,
        source=source,
    )


def choose(
    asset_id: str, asset: Asset, profile: AssetProfile, scene: str | None
) -> tuple[str, Variant, str | None, str]:
    if scene is not None and not token(scene, dotted=False):
        raise AssetSelectionError("scene: invalid lowercase identifier")
    effective = scene or profile.default_scene or asset.variants[asset.default].scene
    specific = f"{asset_id}@{effective}" if effective is not None else ""
    for key in (specific, asset_id):
        if key in profile.overrides:
            name = profile.overrides[key]
            variant = asset.variants[name]
            if variant.scene not in (None, effective):
                raise AssetSelectionError("override: incompatible scene")
            return name, variant, effective, "profile.scene" if key == specific else "profile.asset"
    ranked: dict[tuple[bool, bool], list[str]] = {}
    for name, variant in asset.variants.items():
        if variant.scene not in (None, effective):
            continue
        if profile.theme is not None and variant.theme not in (None, profile.theme):
            continue
        score = (
            effective is not None and variant.scene == effective,
            profile.theme is not None and variant.theme == profile.theme,
        )
        ranked.setdefault(score, []).append(name)
    if not ranked:
        raise AssetSelectionError("selection: no compatible variant")
    best = ranked[max(ranked)]
    if asset.default in best:
        name = asset.default
    elif len(best) == 1:
        name = best[0]
    else:
        raise AssetSelectionError("selection: ambiguous variants")
    return name, asset.variants[name], effective, "manifest"
