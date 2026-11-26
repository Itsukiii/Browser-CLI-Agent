import asyncio
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from bca.lite.cli import main
from bca.lite.cli_config import Settings, load, parser


def test_help_has_no_native_imports(capsys):
    # Separate subprocess is used by installed-wheel evidence for import isolation.
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "--list-targets" in capsys.readouterr().out


def test_paths_and_overrides(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('model="ocr"\nmanifest="model.json"\ninterval=2\nroi=false\n')
    settings = load(parser().parse_args(["--config", str(path), "--interval", "0.75", "--roi"]))
    assert settings.model == tmp_path / "ocr"
    assert settings.manifest == tmp_path / "model.json"
    assert settings.interval == 0.75 and settings.roi
    override = load(
        parser().parse_args(["--config", str(path), "--model", "other", "--manifest", "other.json"])
    )
    assert override.model == Path("other").resolve()


@pytest.mark.parametrize(
    "toml",
    [
        "interval=true",
        "interval=nan",
        "max_frame_age=0",
        "callback_timeout=-1",
        'roi="yes"',
        'plugin="auto"',
        'target=""',
        "model=3",
        'model="ocr"',
        'unknown="value"',
        '[nested]\nendpoint="x"',
        'endpoint="http://example.com"',
        'endpoint="http://user:secret@127.0.0.1:9341"',
        'endpoint="http://127.0.0.1:9341/x"',
        'endpoint="http://127.0.0.1:0"',
        'log_level="TRACE"',
        'target="abc def"',
    ],
)
def test_invalid_config_fails_before_connect(tmp_path, toml):
    path = tmp_path / "bad.toml"
    path.write_text(toml)
    with pytest.raises(ValueError):
        load(parser().parse_args(["--config", str(path)]))


def test_target_creation_is_explicit_and_exclusive():
    with pytest.raises(ValueError):
        load(parser().parse_args(["--target", "abc", "--create-fixture"]))
    assert load(parser().parse_args([])).target is None


def test_list_does_not_bind_or_expose_url(monkeypatch, capsys):
    from bca.core.browser.models import BrowserTarget
    from bca.lite import cli_session

    class Session:
        closed = False

        def __init__(self, endpoint):
            pass

        async def connect(self):
            pass

        async def list_targets(self):
            return [
                BrowserTarget(
                    target_id="page-1",
                    type="page",
                    title="private-title",
                    url="https://user:secret@example.com/private?token=hidden",
                )
            ]

        async def close(self):
            Session.closed = True

    monkeypatch.setattr(cli_session, "BrowserSession", Session)
    asyncio.run(cli_session.list_targets(Settings()))
    output = capsys.readouterr().out
    assert "page-1" in output and "example.com" in output
    assert all(s not in output for s in ("private", "secret", "hidden", "token"))
    assert Session.closed


def test_missing_target_does_not_connect(monkeypatch):
    from bca.lite.cli_session import run
    from bca.lite.vision_resources import OCRModelSpec

    monkeypatch.setattr(OCRModelSpec, "verify", lambda self: self.directory)
    settings = replace(Settings(), model=Path.cwd(), manifest=Path.cwd() / "m.json")
    with pytest.raises(ValueError, match="exact --target"):
        asyncio.run(run(settings, check=False, once=True, create_fixture=False))


def test_check_offline_model_validation():
    import os

    if not os.environ.get("BCA_OCR_MODEL"):
        pytest.skip("explicit model required")
    assert (
        main(
            [
                "--check",
                "--model",
                os.environ["BCA_OCR_MODEL"],
                "--manifest",
                "docs/lite/models/ppocr-v3-en.json",
            ]
        )
        == 0
    )


def test_module_help_without_optional_dependencies(tmp_path):
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "bca.lite", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0 and "bca-lite" in result.stdout
