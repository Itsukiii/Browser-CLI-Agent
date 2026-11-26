"""Test-only lifecycle observer; delegates all operations to production Coordinator."""

import dataclasses
import json
import os
import time
from pathlib import Path

from bca.lite.cli import main
from bca.lite.observation import ObservationCoordinator

original_start = ObservationCoordinator.start
original_close = ObservationCoordinator.aclose
started = None


async def start(self):
    global started
    await original_start(self)
    started = time.monotonic()


async def close(self):
    stats = self.stats
    report = await original_close(self)
    data = {
        "pid": os.getpid(),
        "duration": time.monotonic() - started,
        "stats": dataclasses.asdict(stats),
        "close": dataclasses.asdict(report),
    }
    Path(os.environ["BCA_CLI_METRICS"]).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return report


ObservationCoordinator.start = start
ObservationCoordinator.aclose = close
raise SystemExit(main())
