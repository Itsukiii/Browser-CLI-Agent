"""Summarize recorded process samples by actual PID, never redirector PID alone."""

import json
import sys
from pathlib import Path


def summarize(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    by_pid = {}
    for sample in data["samples"]:
        for row in sample["processes"]:
            by_pid.setdefault(row["pid"], []).append(row)
    rows = []
    for pid, samples in by_pid.items():
        elapsed = samples[-1]["monotonic"] - samples[0]["monotonic"]
        rows.append(
            dict(
                pid=pid,
                scope=samples[0]["scope"],
                sampled_seconds=elapsed,
                cpu_seconds=samples[-1]["cpu_seconds"] - samples[0]["cpu_seconds"],
                mean_cores=(samples[-1]["cpu_seconds"] - samples[0]["cpu_seconds"]) / elapsed
                if elapsed
                else 0,
                peak_rss=max(s["rss"] for s in samples),
                peak_private=max(s["private_bytes"] for s in samples),
            )
        )
    result = dict(source=str(path), exit_code=data["exit_code"], processes=rows)
    path.with_name("metrics-summary.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(summarize(Path(sys.argv[1])), indent=2))
