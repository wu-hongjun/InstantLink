#!/usr/bin/env python3
"""Compile production iOS progress policy on macOS and replay chunk traces."""

import fcntl
import subprocess
import tempfile
from pathlib import Path

directory = Path(__file__).resolve().parent
root = directory.parents[2]
with open("/tmp/instantlink-099-benchmark.lock", "w") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    with tempfile.TemporaryDirectory(prefix="instantlink-ios-progress-") as temporary:
        binary = Path(temporary) / "progress-benchmark"
        subprocess.run(
            [
                "xcrun",
                "swiftc",
                "-O",
                "-parse-as-library",
                str(root / "ios/InstantLink/Services/DownloadProgressReporter.swift"),
                str(directory / "10-ios-progress-benchmark.swift"),
                "-o",
                str(binary),
            ],
            check=True,
            timeout=60,
        )
        subprocess.run([str(binary)], check=True, timeout=60)
