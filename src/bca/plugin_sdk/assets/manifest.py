"""Strict JSON v1 metadata; all declared paths checked without decoding pixels."""

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .errors import AssetManifestError
from .paths import inspect_file, read_file, relative_path

ID = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*\Z")
DIMENSION = re.compile(r"[a-z][a-z0-9_]*\Z")


def token(value: object, *, dotted: bool = True) -> bool:
    return isinstance(value, str) and (ID if dotted else DIMENSION).fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class Variant:
    path: str
    scene: str | None
    theme: str | None
    size: tuple[int, int] | None
    mask: str | None


@dataclass(frozen=True, slots=True)
class Asset:
    default: str
    variants: Mapping[str, Variant]


def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise AssetManifestError("json: duplicate object key")
        result[key] = value
    return result


def finite(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise AssetManifestError("json: non-finite number")
    return number


def fields(value: object, required: set[str], optional: set[str], where: str) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or not required <= value.keys()
        or value.keys() - required - optional
    ):
        raise AssetManifestError(where + ": invalid structure or fields")
    return {str(k): v for k, v in value.items()}


def parse_manifest(root: Path, path: Path) -> Mapping[str, Asset]:
    raw = read_file(root, path)
    try:
        doc: object = json.loads(
            raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=finite, parse_float=finite
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise AssetManifestError("json: invalid UTF-8 document") from exc
    top = fields(doc, {"schema_version", "assets"}, set(), "manifest")
    if type(top["schema_version"]) is not int or top["schema_version"] != 1:
        raise AssetManifestError("schema_version: expected integer 1")
    entries = top["assets"]
    if not isinstance(entries, list):
        raise AssetManifestError("assets: expected array")
    result: dict[str, Asset] = {}
    for index, entry in enumerate(entries):
        where = f"assets[{index}]"
        item = fields(entry, {"id", "default_variant", "variants"}, set(), where)
        asset_id, default, variants = item["id"], item["default_variant"], item["variants"]
        if not token(asset_id) or not token(default):
            raise AssetManifestError(where + ": invalid id or default_variant")
        assert isinstance(asset_id, str) and isinstance(default, str)
        if asset_id in result:
            raise AssetManifestError(where + ": duplicate asset id")
        if not isinstance(variants, dict) or not variants or default not in variants:
            raise AssetManifestError(where + ": invalid variants or missing default")
        parsed: dict[str, Variant] = {}
        for name, value in variants.items():
            if not token(name):
                raise AssetManifestError(where + ".variants: invalid id")
            spec = fields(value, {"path"}, {"scene", "theme", "size", "mask"}, where + ".variant")
            scene, theme = spec.get("scene"), spec.get("theme")
            for key in ("scene", "theme"):
                if key in spec and not token(spec[key], dotted=False):
                    raise AssetManifestError(where + ".variant." + key + ": invalid identifier")
            assert scene is None or isinstance(scene, str)
            assert theme is None or isinstance(theme, str)
            size = None
            if "size" in spec:
                dimensions = spec["size"]
                if (
                    not isinstance(dimensions, list)
                    or len(dimensions) != 2
                    or any(type(n) is not int or n <= 0 for n in dimensions)
                ):
                    raise AssetManifestError(
                        where + ".variant.size: expected positive integer pair"
                    )
                size = (dimensions[0], dimensions[1])
            image = relative_path(spec["path"])
            mask = relative_path(spec["mask"]) if "mask" in spec else None
            inspect_file(root, root / image)
            if mask is not None:
                inspect_file(root, root / mask)
            parsed[name] = Variant(image, scene, theme, size, mask)
        result[asset_id] = Asset(default, MappingProxyType(parsed))
    return MappingProxyType(result)
