"""Explicit, offline resource verification. No downloads or implicit model lookup."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .vision_types import VisionError


@dataclass(frozen=True)
class OCRModelSpec:
    directory: Path
    manifest: Path

    def verify(self) -> Path:
        try:
            root = self.directory.resolve(strict=True)
            data = json.loads(self.manifest.read_text(encoding="utf-8"))
            if not all(data.get(k) for k in ("source", "revision", "license", "upstream")):
                raise ValueError("model provenance/license missing")
            files = data["files"]
            if set(files) != {"det.onnx", "rec.onnx", "keys.txt"}:
                raise ValueError("manifest must identify det.onnx, rec.onnx and keys.txt")
            for name, record in files.items():
                path = (root / name).resolve(strict=True)
                if not path.is_relative_to(root):
                    raise ValueError("model path escapes directory")
                if path.stat().st_size != record["size"]:
                    raise ValueError(f"model size mismatch: {name}")
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if digest != record["sha256"]:
                    raise ValueError(f"model SHA256 mismatch: {name}")
            return root
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise VisionError(f"OCR model verification failed: {exc}") from exc


@dataclass(frozen=True)
class ResourceSpec:
    bundle: Path
    ocr: OCRModelSpec | None = None

    def bundle_path(self) -> Path:
        if not self.bundle.is_absolute() or not self.bundle.is_dir():
            raise VisionError("bundle must be an existing absolute directory")
        # Models must be explicit and verified, not silently picked up from a bundle.
        if (self.bundle / "model" / "ocr").exists():
            raise VisionError("configure OCRModelSpec separately from the template bundle")
        return self.bundle.resolve()


def template_path(bundle: Path, name: str) -> Path:
    root = (bundle / "image").resolve()
    path = (root / name).resolve()
    if not name or Path(name).is_absolute() or not path.is_relative_to(root) or not path.is_file():
        raise VisionError(f"template missing or outside bundle/image: {name}")
    try:
        with Image.open(path) as image:
            image.verify()
    except (OSError, ValueError) as exc:
        raise VisionError(f"invalid template image: {name}") from exc
    return path
