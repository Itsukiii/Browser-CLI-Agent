import importlib
import logging
import pkgutil
import tomllib
from pathlib import Path

import bca


def test_all_packages_import_without_configuring_root_logger():
    handlers = list(logging.getLogger().handlers)
    for module in pkgutil.walk_packages(bca.__path__, "bca."):
        imported = importlib.import_module(module.name)
        for symbol in getattr(imported, "__all__", ()):
            assert hasattr(imported, symbol), f"{module.name}.{symbol}"
    assert logging.getLogger().handlers == handlers


def test_sample_configuration():
    with (Path(__file__).parents[2] / "configs/default.toml").open("rb") as stream:
        config = tomllib.load(stream)
    assert config["logging"]["level"] == "INFO"
    assert config["plugin"]["config"]["page_id"] == "demo"
