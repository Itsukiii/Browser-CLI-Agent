"""Derive auditable aggregates from preserved raw samples, never replace raw evidence."""

import json
import statistics
import sys
from pathlib import Path


def distribution(values):
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "median": statistics.median(ordered),
        "p95": ordered[max(0, int(len(ordered) * 0.95 + 0.999) - 1)],
        "min": ordered[0],
        "max": ordered[-1],
    }


def main():
    root = Path(sys.argv[1])
    summary = {"processes": {}, "sustained": {}}
    for file in sorted(root.glob("*/process.json")):
        source = json.loads(file.read_text(encoding="utf-8"))
        samples = source["samples"]
        # Earlier diagnostics measured only the Windows venv launcher; exclude.
        if not samples or "processes" not in samples[0]:
            continue
        scopes = {}
        for scope in ("workload", "isolated_edge"):
            series = []
            for sample in samples:
                rows = [r for r in sample["processes"] if r.get("scope", "workload") == scope]
                if not rows:
                    continue
                series.append(
                    {
                        "time": sample["monotonic"],
                        **{
                            key: sum(r[key] for r in rows)
                            for key in ("rss", "private_bytes", "cpu_seconds", "threads", "handles")
                        },
                    }
                )
            if not series:
                continue
            elapsed = series[-1]["time"] - series[0]["time"]
            # Sum maximum cumulative CPU per PID; processes may exit before the
            # final sample. This reports consumed core-seconds, not % of all CPUs.
            pid_cpu = {}
            for sample in samples:
                for row in sample["processes"]:
                    if row.get("scope", "workload") == scope:
                        values = pid_cpu.setdefault(row["pid"], [])
                        values.append(row["cpu_seconds"])
            cpu = sum(max(v) - min(v) for v in pid_cpu.values())
            scopes[scope] = {
                "seconds": elapsed,
                "cpu_core_percent": cpu / elapsed * 100,
                "first": series[0],
                "last": series[-1],
                "peak": {
                    key: max(s[key] for s in series)
                    for key in ("rss", "private_bytes", "threads", "handles")
                },
            }
        all_rows = [r for s in samples for r in s["processes"]]
        summary["processes"][file.parent.name] = {
            "exit_code": source["exit_code"],
            "scopes": scopes,
            "min_system_available": min(r["system_available"] for r in all_rows),
            "peak_system_commit": max(r["system_commit"] for r in all_rows),
            "system_commit_limit": all_rows[0]["system_commit_limit"],
        }
    for file in root.glob("*/data/sustained/report.json"):
        report = json.loads(file.read_text(encoding="utf-8"))
        records = report["records"]
        row = {
            key: report.get(key)
            for key in (
                "status",
                "duration",
                "stats",
                "effective_hz",
                "close",
                "cleanup",
                "handles_after",
            )
        }
        row["timing_seconds"] = {
            key: distribution([r[key] for r in records if r[key] is not None])
            for key in ("capture", "native", "parse", "total")
        }
        row["completion_interval_seconds"] = distribution(
            [b["completed"] - a["completed"] for a, b in zip(records, records[1:], strict=False)]
        )
        summary["sustained"][file.parents[2].name] = row
    (root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
