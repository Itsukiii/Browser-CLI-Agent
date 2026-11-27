"""Owned Quiz page resource lifetime; no browser state is read here."""

import base64
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import as_file, files
from pathlib import Path


@contextmanager
def quiz_bundle() -> Iterator[Path]:
    with as_file(files("bca.lite").joinpath("resources/quiz")) as path:
        yield path.resolve()


def quiz_html(bundle: Path) -> str:
    page = (
        (bundle / "page.html")
        .read_text(encoding="utf-8")
        .replace(
            '<script src="quiz.js"></script>',
            "<script>" + (bundle / "quiz.js").read_text(encoding="utf-8") + "</script>",
        )
    )
    for name in ("neutral", "selected"):
        encoded = base64.b64encode((bundle / f"image/{name}.png").read_bytes()).decode("ascii")
        page = page.replace(f"image/{name}.png", "data:image/png;base64," + encoded)
    return page


@contextmanager
def quiz_vision_bundle() -> Iterator[Path]:
    """Prepare finite scale templates from originals, never screenshot crops."""
    from PIL import Image

    with quiz_bundle() as source, tempfile.TemporaryDirectory(prefix="bca-quiz-") as directory:
        bundle = Path(directory) / "quiz"
        shutil.copytree(source, bundle)
        for name in ("neutral", "selected"):
            with Image.open(source / f"image/{name}.png") as image:
                for size in range(8, 129):
                    image.resize((size, size), Image.Resampling.BILINEAR).save(
                        bundle / f"image/{name}-{size}.png"
                    )
        yield bundle
