"""Run any command in a fresh child, preserve streams and Windows resource samples.

python -m tests.lite.stability_probe OUTPUT -- python -m pytest ...
Uses psutil only in the external test monitor, not in the application/native child.
"""

import ctypes
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil


def sample(process):
    memory = process.memory_info()
    cpu = process.cpu_times()

    # PERFORMANCE_INFORMATION reports system commit, unlike pagefile use alone.
    class Performance(ctypes.Structure):
        _fields_ = (
            [("cb", ctypes.c_ulong)]
            + [
                (key, ctypes.c_size_t)
                for key in (
                    "CommitTotal",
                    "CommitLimit",
                    "CommitPeak",
                    "PhysicalTotal",
                    "PhysicalAvailable",
                    "SystemCache",
                    "KernelTotal",
                    "KernelPaged",
                    "KernelNonpaged",
                    "PageSize",
                )
            ]
            + [(key, ctypes.c_ulong) for key in ("HandleCount", "ProcessCount", "ThreadCount")]
        )

    info = Performance()
    info.cb = ctypes.sizeof(info)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
        raise ctypes.WinError()
    return {
        "monotonic": time.monotonic(),
        "pid": process.pid,
        "rss": memory.rss,
        "private_bytes": memory.private,
        "cpu_seconds": cpu.user + cpu.system,
        "threads": process.num_threads(),
        "handles": process.num_handles(),
        "system_available": info.PhysicalAvailable * info.PageSize,
        "system_commit": info.CommitTotal * info.PageSize,
        "system_commit_limit": info.CommitLimit * info.PageSize,
    }


def main():
    path = Path(sys.argv[1])
    path.mkdir(parents=True, exist_ok=False)  # Never overwrite a failed run.
    command = sys.argv[3:]
    report = {
        "command": command,
        "start": datetime.now(UTC).isoformat(),
        "monitor_psutil": psutil.__version__,
        "cwd": str(Path.cwd()),
        "samples": [],
    }
    browser = None
    if os.environ.get("BCA_CDP_ENDPOINT") == "http://127.0.0.1:9341":
        for candidate in psutil.process_iter(["name", "cmdline"]):
            args = candidate.info["cmdline"] or []
            if (
                candidate.info["name"] == "msedge.exe"
                and "--remote-debugging-port=9341" in args
                and not any(arg.startswith("--type=") for arg in args)
            ):
                if browser is not None:
                    raise RuntimeError("multiple isolated Edge roots; monitor scope ambiguous")
                browser = candidate
        report["isolated_browser_pid"] = browser.pid if browser else None
    with (path / "stdout.txt").open("wb") as out, (path / "stderr.txt").open("wb") as err:
        child = subprocess.Popen(command, stdout=out, stderr=err)
        report["pid"] = child.pid
        process = psutil.Process(child.pid)
        while child.poll() is None:
            try:
                # Windows venv python.exe may be a redirector whose child owns
                # the DLLs. Preserve each PID, not the idle launcher as workload.
                members = [(p, "workload") for p in [process, *process.children(recursive=True)]]
                if browser is not None:
                    members += [
                        (p, "isolated_edge") for p in [browser, *browser.children(recursive=True)]
                    ]
                rows = []
                for member, scope in members:
                    try:
                        rows.append({"scope": scope, **sample(member)})
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                report["samples"].append({"monotonic": time.monotonic(), "processes": rows})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            time.sleep(0.25)
        report["exit_code"] = child.wait()
    report["end"] = datetime.now(UTC).isoformat()
    (path / "process.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "samples"}), flush=True)
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
