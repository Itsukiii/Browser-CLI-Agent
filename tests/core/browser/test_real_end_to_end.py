import asyncio
import os
from pathlib import Path

import pytest

from examples.browser_end_to_end import run_end_to_end


@pytest.mark.browser_integration
@pytest.mark.skipif(
    not os.environ.get("BCA_CDP_ENDPOINT"), reason="set BCA_CDP_ENDPOINT for integration"
)
def test_real_browser_subsystem_end_to_end(tmp_path):
    output = Path(os.environ.get("BCA_BROWSER_OUTPUT", str(tmp_path)))
    report = asyncio.run(run_end_to_end(os.environ["BCA_CDP_ENDPOINT"], output))
    assert report["status"] == "passed"
    assert len(report["observations"]) == 18
    assert report["preexisting_targets_preserved"] is True
    assert report["owned_targets_remaining"] == []
    assert report["session_ready_after_providers_close"] is True
    assert report["cleanup"] == {
        "pending_count": 0,
        "reader_running": False,
        "connected": False,
        "errors": [],
    }
