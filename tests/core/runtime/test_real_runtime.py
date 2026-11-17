import asyncio
import os

import pytest

from examples.runtime_browser import run_checks


@pytest.mark.browser_integration
@pytest.mark.skipif(
    not os.environ.get("BCA_CDP_ENDPOINT"), reason="set BCA_CDP_ENDPOINT for runtime Browser smoke"
)
def test_real_runtime_freshness():
    report = asyncio.run(run_checks(os.environ["BCA_CDP_ENDPOINT"]))
    assert report["initial"] == "succeeded"
    assert report["after_scroll"] == "stale"
    assert report["after_observe"] == "succeeded"

    assert report["after_recovery"] == "succeeded"
