"""Trusted-root checks and read-time identity verification, not an OS sandbox."""

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .errors import AssetPathError

MAX_FILE_BYTES = 128 * 1024 * 1024


def relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise AssetPathError("path: expected nonempty POSIX relative path")
    parts = value.split("/")
    for part in parts:
        if (
            part in ("", ".", "..")
            or part.endswith((" ", "."))
            or any(ord(c) < 32 or ord(c) == 127 or c in '\\:<>"|?*' for c in part)
            or re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])", part.split(".")[0])
        ):
            raise AssetPathError("path: invalid relative component")
    return value


def root_directory(root: Path) -> Path:
    try:
        resolved = root.resolve(strict=True)
        if not resolved.is_dir():
            raise AssetPathError("root: expected directory")
        return resolved
    except (OSError, ValueError, RuntimeError) as exc:
        raise AssetPathError("root: unavailable directory") from exc


@dataclass(frozen=True, slots=True)
class FileIdentity:
    path: Path
    device: int
    inode: int
    size: int
    modified_ns: int


def identity(path: Path, info: os.stat_result) -> FileIdentity:
    if not stat.S_ISREG(info.st_mode):
        raise AssetPathError("resource: expected regular file")
    # Windows path stat and descriptor fstat can disagree on ctime semantics.
    # Device/inode/size/mtime are comparable on both paths and handles.
    return FileIdentity(path, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def inspect_file(root: Path, path: Path) -> FileIdentity:
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise AssetPathError("resource: outside configured root")
        return identity(resolved, resolved.stat())
    except (OSError, ValueError, RuntimeError) as exc:
        raise AssetPathError("resource: missing or inaccessible file") from exc


def read_file(root: Path, path: Path, expected: FileIdentity | None = None) -> bytes:
    before = inspect_file(root, path)
    if expected is not None and before != expected:
        raise AssetPathError("resource: identity changed before read")
    if before.size > MAX_FILE_BYTES:
        raise AssetPathError("resource: encoded file exceeds 128 MiB limit")
    try:
        with before.path.open("rb") as stream:
            if identity(before.path, os.fstat(stream.fileno())) != before:
                raise AssetPathError("resource: identity changed at open")
            data = stream.read(MAX_FILE_BYTES + 1)
            if identity(before.path, os.fstat(stream.fileno())) != before:
                raise AssetPathError("resource: identity changed during read")
        if len(data) != before.size or inspect_file(root, path) != before:
            raise AssetPathError("resource: identity changed after read")
        return data
    except OSError as exc:
        raise AssetPathError("resource: read failed") from exc
