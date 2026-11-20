import sys
from pathlib import Path

import pytest

from bca.core.plugins import (
    PluginCatalog,
    PluginCompatibilityError,
    PluginContractError,
    PluginDuplicateIdError,
    PluginLoader,
    PluginLoadError,
)

EXAMPLE = Path(__file__).resolve().parents[3] / "plugins" / "example"


def candidate(root, name="one", plugin_id="example", source=None):
    path = root / name
    path.mkdir(parents=True)
    manifest = (EXAMPLE / "plugin.toml").read_text(encoding="utf-8")
    (path / "plugin.toml").write_text(
        manifest.replace('"example"', f'"{plugin_id}"'), encoding="utf-8"
    )
    (path / "__init__.py").write_text(
        source if source is not None else (EXAMPLE / "__init__.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return path


def test_static_scan_duplicates_and_missing_root(tmp_path):
    candidate(tmp_path, "a", source="raise RuntimeError('never import')")
    candidate(tmp_path, "b", source="raise RuntimeError('never import')")
    candidate(tmp_path, "c", "other", source="raise RuntimeError('never import')")
    catalog = PluginCatalog([tmp_path, tmp_path / "absent"])
    result = catalog.discover()
    assert [d.plugin_id for d in result.candidates] == ["other"]
    assert len(result.issues) == 3
    assert sum(i.plugin_id == "example" for i in result.issues) == 2
    with pytest.raises(PluginDuplicateIdError):
        catalog.get("example")


@pytest.mark.parametrize(
    "bad", ["missing", "syntax", "protocol", "bool", "capabilities", "factory", "entry", "field"]
)
def test_bad_manifest_is_isolated(tmp_path, bad):
    p = candidate(tmp_path)
    manifest = p / "plugin.toml"
    text = manifest.read_text()
    if bad == "missing":
        manifest.unlink()
    elif bad == "entry":
        (p / "__init__.py").unlink()
    else:
        text = {
            "syntax": "[",
            "protocol": text.replace("= 2", "= 3"),
            "bool": text.replace("= 2", "= true"),
            "capabilities": text.replace('["capture", "input"]', '["input", "input"]'),
            "factory": text.replace('"create_plugin"', '"not valid"'),
            "field": text + "unknown = 1\n",
        }[bad]
        manifest.write_text(text)
    candidate(tmp_path, "valid", "valid")
    result = PluginCatalog([tmp_path]).discover()
    assert len(result.issues) == 1 and len(result.candidates) == 1


def test_relative_packages_cached_and_independent(tmp_path, monkeypatch):
    source = (EXAMPLE / "__init__.py").read_text(encoding="utf-8")
    paths = []
    for root, value in ((tmp_path / "a", 1), (tmp_path / "b", 2)):
        p = candidate(root, source=source + "\nfrom .worker import VALUE\n")
        (p / "worker.py").write_text(f"VALUE={value}\n")
        paths.append(p)
    descriptors = [PluginCatalog([p.parent]).discover().candidates[0] for p in paths]
    monkeypatch.chdir(tmp_path)
    loader = PluginLoader()
    a, b = (loader.load(d) for d in descriptors)
    assert type(a) is not type(b)
    assert sys.modules[type(a).__module__].VALUE == 1
    assert sys.modules[type(b).__module__].VALUE == 2
    again = PluginLoader().load(descriptors[0])
    assert again is not a and type(again) is type(a)


def test_import_rollback(tmp_path):
    p = candidate(tmp_path, source="from . import worker\nraise RuntimeError('private')\n")
    (p / "worker.py").write_text("VALUE=1\n")
    d = PluginCatalog([tmp_path]).discover().candidates[0]
    before = set(sys.modules)
    with pytest.raises(PluginLoadError) as error:
        PluginLoader().load(d)
    assert isinstance(error.value.__cause__, RuntimeError)
    assert not [n for n in set(sys.modules) - before if n.startswith("_bca_plugin_")]


@pytest.mark.parametrize(
    "tail,kind",
    [
        ("create_plugin=None", PluginLoadError),
        ("def create_plugin(required): return ExamplePlugin()", PluginLoadError),
        ("def create_plugin(): raise RuntimeError('private')", PluginLoadError),
        ("def create_plugin(): return object()", PluginContractError),
        (
            "ExamplePlugin.metadata=PluginMetadata(plugin_id='different',version='0.2.0')",
            PluginCompatibilityError,
        ),
        ("ExamplePlugin.observe=lambda self: None", PluginContractError),
    ],
)
def test_load_boundaries(tmp_path, tail, kind):
    p = candidate(tmp_path)
    with (p / "__init__.py").open("a", encoding="utf-8") as f:
        f.write("\n" + tail + "\n")
    descriptor = PluginCatalog([tmp_path]).discover().candidates[0]
    with pytest.raises(kind):
        PluginLoader().load(descriptor)


def test_read_failure_and_resolved_escape_are_isolated(tmp_path, monkeypatch):
    one = candidate(tmp_path, "one")
    two = candidate(tmp_path, "two", "other")
    real_open = Path.open
    real_resolve = Path.resolve

    def blocked_open(path, *args, **kwargs):
        if path == one / "plugin.toml":
            raise PermissionError("private")
        return real_open(path, *args, **kwargs)

    def escaped(path, *args, **kwargs):
        if path == two:
            return tmp_path.parent / "external"
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", blocked_open)
    monkeypatch.setattr(Path, "resolve", escaped)
    result = PluginCatalog([tmp_path]).discover()
    assert not result.candidates
    assert {i.error_type for i in result.issues} == {"PermissionError", "PluginManifestError"}


def test_manifest_file_escape_rejected(tmp_path, monkeypatch):
    p = candidate(tmp_path)
    original = Path.resolve

    def escaped(path, *args, **kwargs):
        if path == p / "__init__.py":
            return tmp_path.parent / "outside.py"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", escaped)
    result = PluginCatalog([tmp_path]).discover()
    assert not result.candidates and result.issues[0].error_type == "PluginManifestError"
