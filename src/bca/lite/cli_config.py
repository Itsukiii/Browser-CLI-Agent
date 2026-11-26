"""Strict, offline CLI settings; relative paths belong to their config file."""

from __future__ import annotations

import argparse
import ipaddress
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    endpoint: str = "http://127.0.0.1:9341"
    target: str | None = None
    plugin: str = "fixture"
    model: Path | None = None
    manifest: Path | None = None
    interval: float = 0.75
    callback_timeout: float = 10.0
    max_frame_age: float = 2.0
    log_level: str = "WARNING"
    roi: bool = True


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="bca-lite", description="Maa visual browser CLI")
    result.add_argument("--config", type=Path, help="explicit TOML file; no automatic search")
    result.add_argument("--endpoint", help="loopback HTTP CDP origin")
    result.add_argument("--target", help="exact page Target ID; never a title/URL substring")
    result.add_argument("--plugin", choices=["fixture"], help="installed built-in business plugin")
    result.add_argument("--model", type=Path, help="explicit OCR directory (not downloaded)")
    result.add_argument("--manifest", type=Path, help="OCR source/license/SHA256 JSON")
    for key in ("interval", "callback-timeout", "max-frame-age"):
        result.add_argument("--" + key, type=float)
    result.add_argument("--log-level", choices=["ERROR", "WARNING", "INFO", "DEBUG"])
    result.add_argument("--roi", action=argparse.BooleanOptionalAction, default=None)
    modes = result.add_mutually_exclusive_group()
    modes.add_argument("--list-targets", action="store_true", help="list IDs; no native startup")
    modes.add_argument("--check", action="store_true", help="validate config/resources offline")
    modes.add_argument("--once", action="store_true", help="one new visual observation then close")
    result.add_argument("--create-fixture", action="store_true", help="create and own a demo page")
    return result


def load(args: argparse.Namespace) -> Settings:
    values: dict[str, object] = {}
    if args.config is not None:
        with args.config.open("rb") as stream:
            values = tomllib.load(stream)
        unknown = values.keys() - Settings.__dataclass_fields__.keys()
        if unknown:
            raise ValueError("unknown configuration keys: " + ", ".join(sorted(unknown)))
        for key in ("model", "manifest"):
            if key in values:
                if not isinstance(values[key], str) or not values[key]:
                    raise ValueError(f"{key} must be a nonempty path string")
                values[key] = (args.config.resolve().parent / str(values[key])).resolve()
    for key in Settings.__dataclass_fields__:
        value = getattr(args, key, None)
        if value is not None:
            values[key] = value.resolve() if isinstance(value, Path) else value
    defaults = Settings()
    for key in ("endpoint", "plugin", "log_level"):
        if not isinstance(values.get(key, getattr(defaults, key)), str):
            raise ValueError(f"{key} must be a string")
    if "target" in values and (
        not isinstance(values["target"], str)
        or not values["target"]
        or any(c.isspace() or ord(c) < 32 for c in str(values["target"]))
    ):
        raise ValueError("target must be one nonempty exact ID")
    for key in ("interval", "callback_timeout", "max_frame_age"):
        value = values.get(key, getattr(defaults, key))
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(f"{key} must be positive and finite")
    if type(values.get("roi", True)) is not bool:
        raise ValueError("roi must be a boolean")
    settings = Settings(**values)  # type: ignore[arg-type]
    url = urlsplit(settings.endpoint)
    try:
        local = url.hostname == "localhost" or ipaddress.ip_address(url.hostname or "").is_loopback
    except ValueError:
        local = False
    if not (
        local
        and url.scheme == "http"
        and url.path in ("", "/")
        and url.port != 0
        and url.username is None
        and url.password is None
        and not url.query
        and not url.fragment
        and not any(c.isspace() for c in settings.endpoint)
    ):
        raise ValueError("endpoint must be a loopback HTTP origin without credentials/query")
    if settings.plugin != "fixture":
        raise ValueError("unknown plugin; installed choices: fixture")
    if settings.log_level not in ("ERROR", "WARNING", "INFO", "DEBUG"):
        raise ValueError("unsupported log_level")
    if bool(settings.model) != bool(settings.manifest):
        raise ValueError("model and manifest must be supplied together")
    if args.create_fixture and settings.target:
        raise ValueError("--create-fixture and target are mutually exclusive")
    if args.create_fixture and (args.check or args.list_targets):
        raise ValueError("--create-fixture requires an observation session")
    return settings
