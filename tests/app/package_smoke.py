"""Run with a clean environment's python -I after installing the built wheel."""

import importlib
import importlib.metadata
import importlib.util
import pkgutil
import sys
from pathlib import Path

import bca
from bca.core.protocol import (
    PROTOCOL_VERSION,
    Action,
    ActionType,
    Frame,
    ImageFormat,
    Viewport,
    from_json,
    to_dict,
    to_json,
)


def main() -> None:
    assert bca.__version__ == "0.2.0"
    assert PROTOCOL_VERSION == 2
    location = Path(bca.__file__).resolve()
    assert "site-packages" in location.parts, location
    assert location.is_relative_to(Path(sys.prefix).resolve()), location
    assert importlib.util.find_spec("pydantic") is None
    requirements = importlib.metadata.requires("browser-cli-agent") or []
    runtime = [item for item in requirements if "extra ==" not in item]
    assert len(runtime) == 1 and runtime[0].startswith("websockets"), requirements
    assert importlib.metadata.version("websockets").startswith("15.")
    modules = list(pkgutil.walk_packages(bca.__path__, "bca."))
    for module in modules:
        imported = importlib.import_module(module.name)
        for symbol in getattr(imported, "__all__", ()):
            assert hasattr(imported, symbol)
    assert location.with_name("py.typed").is_file()
    frame = Frame(
        width=2,
        height=2,
        data=b"\x89PNG\r\n\x1a\nfixture",
        format=ImageFormat.PNG,
        page_id="smoke",
        viewport=Viewport(width=100, height=100, capture_width=100, capture_height=100),
    )
    assert "data" not in to_dict(frame)
    assert from_json(Frame, to_json(frame, include_frame_data=True)) == frame
    action = Action(page_id="smoke", type=ActionType.TEXT_INPUT, text="test")
    assert from_json(Action, to_json(action)) == action
    print(
        f"Clean wheel acceptance passed: {len(modules)} modules; websockets runtime dependency; "
        "typed marker; metadata boundary; binary and action round trips"
    )


if __name__ == "__main__":
    main()
