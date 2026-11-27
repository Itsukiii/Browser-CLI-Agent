"""Owned Quiz page resource lifetime; no browser state is read here."""

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import as_file, files
from pathlib import Path


@contextmanager
def quiz_bundle() -> Iterator[Path]:
    with as_file(files("bca.lite").joinpath("resources/quiz")) as path:
        yield path.resolve()


def quiz_html(bundle: Path) -> str:
    return (
        (bundle / "page.html")
        .read_text(encoding="utf-8")
        .replace(
            '<script src="quiz.js"></script>',
            "<script>" + (bundle / "quiz.js").read_text(encoding="utf-8") + "</script>",
        )
    )
