"""Prevent reverse layer imports and cycles as the skeleton grows."""

import ast
import importlib.util
import sys
from pathlib import Path

import bca


def test_layer_dependencies_and_cycles():
    root = Path(bca.__file__).parent
    graph = {}
    for path in root.rglob("*.py"):
        parts = path.relative_to(root).with_suffix("").parts
        name = ".".join(("bca", *parts))
        if name.endswith(".__init__"):
            name = name.removesuffix(".__init__")
            package = name
        else:
            package = name.rpartition(".")[0]
        dependencies = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                dependencies.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                target = "." * node.level + (node.module or "")
                dependencies.add(importlib.util.resolve_name(target, package))
        graph[name] = {dep for dep in dependencies if dep.startswith("bca.")}
        if name.startswith("bca.core"):
            assert not any(dep.startswith(("bca.app", "bca.plugin_sdk")) for dep in graph[name])
        if name.startswith("bca.core.protocol"):
            assert all(
                dep.startswith("bca.") or dep.split(".")[0] in sys.stdlib_module_names
                for dep in dependencies
            )
            assert all(
                dep.startswith(("bca.core.protocol", "bca.core.errors")) for dep in graph[name]
            )
        if name.startswith("bca.core.providers"):
            assert all(
                dep.startswith(("bca.core.providers", "bca.core.protocol", "bca.core.errors"))
                for dep in graph[name]
            )

    visited = set()
    active = set()

    def visit(name):
        assert name not in active, f"circular dependency: {name}"
        if name in visited:
            return
        active.add(name)
        for dependency in graph.get(name, ()):
            visit(dependency)
        active.remove(name)
        visited.add(name)

    for name in graph:
        visit(name)
