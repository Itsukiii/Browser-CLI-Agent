import json
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def assets_root(tmp_path):
    shutil.copytree(Path(__file__).parent / "fixtures", tmp_path, dirs_exist_ok=True)
    return tmp_path


@pytest.fixture
def manifest(assets_root):
    def write(variants=None, default="dialog.default", extras=()):
        doc = {
            "schema_version": 1,
            "assets": [
                {
                    "id": "ui.confirm",
                    "default_variant": default,
                    "variants": variants
                    or {
                        "dialog.default": {
                            "path": "rgb.png",
                            "scene": "dialog",
                            "theme": "default",
                            "size": [2, 1],
                        },
                        "dialog.dark": {"path": "dark.png", "scene": "dialog", "theme": "dark"},
                        "toolbar.default": {"path": "rgb.png", "scene": "toolbar"},
                    },
                }
            ]
            + list(extras),
        }
        (assets_root / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
        return doc

    write()
    return write


@pytest.fixture
def profile(assets_root):
    def write(body="[profile]\nname=dark\ntheme=dark\ndefault_scene=dialog\n", name="profile.ini"):
        (assets_root / name).write_text(body, encoding="utf-8")
        return Path(name)

    return write
