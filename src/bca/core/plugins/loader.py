"""Import selected trusted packages without changing cwd or sys.path."""

import hashlib
import importlib.util
import inspect
import os
import sys
from types import ModuleType

from .catalog import read_descriptor
from .contracts import Plugin
from .errors import PluginLoadError
from .models import PluginDescriptor
from .validation import validate_plugin


class PluginLoader:
    def load(self, descriptor: PluginDescriptor) -> Plugin:
        try:
            path = descriptor.directory.resolve(strict=True)
            current = read_descriptor(path, path.parent)
            if current != descriptor:
                raise PluginLoadError("manifest changed after discovery")
        except Exception as exc:
            raise PluginLoadError("selected plugin files are no longer valid") from exc
        namespace = (
            "_bca_plugin_" + hashlib.sha256(os.path.normcase(str(path)).encode()).hexdigest()
        )
        # A top-level private package avoids shared parent-package rollback races.
        module = sys.modules.get(namespace)
        if module is None:
            before = set(sys.modules)
            try:
                spec = importlib.util.spec_from_file_location(
                    namespace, path / "__init__.py", submodule_search_locations=[str(path)]
                )
                if spec is None or spec.loader is None:
                    raise PluginLoadError("cannot construct plugin module spec")
                module = importlib.util.module_from_spec(spec)
                sys.modules[namespace] = module
                spec.loader.exec_module(module)
            except BaseException as exc:
                for name in set(sys.modules) - before:
                    if name == namespace or name.startswith(namespace + "."):
                        del sys.modules[name]
                if not isinstance(exc, Exception):
                    raise
                raise PluginLoadError("plugin import failed") from exc
        return self._create(module, descriptor)

    def _create(self, module: ModuleType, descriptor: PluginDescriptor) -> Plugin:
        factory = getattr(module, descriptor.factory, None)
        if not callable(factory) or inspect.iscoroutinefunction(factory):
            raise PluginLoadError("plugin factory must be a synchronous callable")
        try:
            inspect.signature(factory).bind()
        except (TypeError, ValueError) as exc:
            raise PluginLoadError("plugin factory must accept no arguments") from exc
        try:
            instance: object = factory()
        except Exception as exc:
            raise PluginLoadError("plugin factory failed") from exc
        if inspect.iscoroutine(instance):
            instance.close()
            raise PluginLoadError("plugin factory returned a coroutine")
        return validate_plugin(instance, descriptor)
