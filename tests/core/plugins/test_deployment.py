"""Actual filesystem and child-process deployment checks, including Windows privileges."""

import errno
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from bca.core.plugins import PluginCatalog, PluginLoader, PluginLoadError

ROOT = Path(__file__).resolve().parents[3]


def test_external_absolute_root_relative_import_and_foreign_cwd(tmp_path):
    with tempfile.TemporaryDirectory(prefix="bca-03.2-") as directory:
        external = Path(directory)
        assert not external.is_relative_to(ROOT)
        plugin = external / "plugins" / "example"
        plugin.mkdir(parents=True)
        shutil.copy2(ROOT / "plugins/example/plugin.toml", plugin / "plugin.toml")
        shutil.copy2(ROOT / "plugins/example/__init__.py", plugin / "implementation.py")
        (plugin / "__init__.py").write_text(
            "from .implementation import create_plugin\n", encoding="utf-8"
        )
        command = """
import json, sys
from pathlib import Path
from bca.core.plugins import PluginCatalog, PluginLoader
catalog=PluginCatalog([Path(sys.argv[1])]); snapshot=catalog.discover()
assert len(snapshot.candidates)==1 and not snapshot.issues
loader=PluginLoader()
first=loader.load(catalog.get('example'))
second=loader.load(catalog.get('example'))
assert first is not second and type(first) is type(second)
print(json.dumps({'outside_repo': True, 'relative_import': True, 'fresh_instances': True}))
"""
        result = subprocess.run(
            [sys.executable, "-c", command, str(plugin.parent)],
            cwd=external,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        report = json.loads(result.stdout)
        duplicate = plugin.parent / "duplicate"
        shutil.copytree(plugin, duplicate)
        snapshot = PluginCatalog([plugin.parent]).discover()
        assert not snapshot.candidates
        assert all(i.error_type == "PluginDuplicateIdError" for i in snapshot.issues)
        report["duplicate_diagnostics"] = len(snapshot.issues)
        (duplicate / "plugin.toml").unlink()
        snapshot = PluginCatalog([plugin.parent]).discover()
        assert (
            len(snapshot.candidates) == 1 and snapshot.issues[0].error_type == "FileNotFoundError"
        )
        (plugin / "plugin.toml").write_text(
            (plugin / "plugin.toml")
            .read_text(encoding="utf-8")
            .replace('factory = "create_plugin"', 'factory = "missing"'),
            encoding="utf-8",
        )
        # Existing manifest has explicit factory; fail at load, never guess an alternative.
        catalog = PluginCatalog([plugin.parent])
        catalog.discover()
        try:
            PluginLoader().load(catalog.get("example"))
        except PluginLoadError:
            report["illegal_entry"] = "PluginLoadError"
        else:
            raise AssertionError("missing factory accepted")
        (tmp_path / "deployment.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def test_actual_symlink_escape_or_explicit_privilege_limit(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    report = {}
    try:
        os.symlink(outside, root / "escape", target_is_directory=True)
    except OSError as exc:
        assert getattr(exc, "winerror", None) == 1314 or exc.errno in (errno.EPERM, errno.EACCES)
        report.update(
            status="not_verified",
            error_type=type(exc).__name__,
            winerror=getattr(exc, "winerror", None),
        )
    else:
        catalog = PluginCatalog([root]).discover()
        assert not catalog.candidates and catalog.issues[0].error_type == "PluginManifestError"
        report.update(status="passed", error_type=catalog.issues[0].error_type)
    (tmp_path / "symlink.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
