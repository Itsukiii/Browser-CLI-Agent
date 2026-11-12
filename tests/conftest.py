import importlib.util
from pathlib import Path

import pytest

from bca.core.protocol import Frame, ImageFormat, Viewport


@pytest.fixture
def frame():
    return Frame(
        width=2,
        height=1,
        data=b"\x89PNG\r\n\x1a\n" + b"fixture",
        format=ImageFormat.PNG,
        page_id="demo",
        viewport=Viewport(
            width=100,
            height=80,
            capture_x=10,
            capture_y=20,
            capture_width=40,
            capture_height=20,
            device_scale_factor=2,
        ),
    )


@pytest.fixture
def example_class():
    path = Path(__file__).parents[1] / "plugins" / "example" / "__init__.py"
    spec = importlib.util.spec_from_file_location("bca_example_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ExamplePlugin
