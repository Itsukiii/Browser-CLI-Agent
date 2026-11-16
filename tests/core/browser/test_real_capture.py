"""Opt-in screenshots on disposable test targets only."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from examples.capture_browser import run_capture_checks


@pytest.mark.browser_integration
@pytest.mark.skipif(
    not os.environ.get("BCA_CDP_ENDPOINT"), reason="set BCA_CDP_ENDPOINT for real capture"
)
def test_real_capture_coordinates_and_cleanup(tmp_path):
    output = Path(os.environ.get("BCA_CAPTURE_OUTPUT", str(tmp_path)))
    report = asyncio.run(run_capture_checks(os.environ["BCA_CDP_ENDPOINT"], output))
    print(f"Capture artifacts: {output.resolve()}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert report["status"] == "passed"
    assert report["closed_target_rejected"] is True
    assert report["canvas_changed_color"] is True
    assert len(report["geometry"]) == 3  # DPR 1 / 1.5 / 2, including both scrollbars.
    assert any(item["file"].endswith("-edge.png") for item in report["captures"])
