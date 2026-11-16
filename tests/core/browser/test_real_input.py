import asyncio
import os
from pathlib import Path

import pytest

from examples.input_browser import run_input_checks


@pytest.mark.browser_integration
@pytest.mark.skipif(
    not os.environ.get("BCA_CDP_ENDPOINT"), reason="set BCA_CDP_ENDPOINT for real input"
)
def test_real_input_and_capture_coordinates(tmp_path):
    output = Path(os.environ.get("BCA_INPUT_OUTPUT", str(tmp_path)))
    report = asyncio.run(run_input_checks(os.environ["BCA_CDP_ENDPOINT"], output))
    assert report["status"] == "passed"
    assert len(report["landings"]) == 6
    assert report["cleanup"] == {"pending_count": 0, "reader_running": False, "connected": False}
    assert len(report["timings_ms"]) == 7
