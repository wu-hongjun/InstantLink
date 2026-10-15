#!/usr/bin/env python3
"""Compile outside measured timings; serialize compiler/bench load with audit peers."""

import fcntl
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCES = [
    "macos/InstantLink/Features/Editor/State/AdjustmentState.swift",
    "macos/InstantLink/Features/Editor/Pipeline/Sections/CurvesLevelsPipeline.swift",
    "macos/Tests/CurvesLevelsReference.swift",
    "macos/Tests/CurvesLevelsFixtures.swift",
    "docs/assets/performance-audit-099/08-app-imaging-benchmark.swift",
]
with tempfile.TemporaryDirectory(prefix="instantlink-curves-benchmark-") as directory:
    executable = Path(directory) / "benchmark"
    with open("/tmp/instantlink-099-benchmark.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        subprocess.run(
            [
                "swiftc",
                "-O",
                "-target",
                "arm64-apple-macosx15.0",
                *[str(ROOT / source) for source in SOURCES],
                "-framework",
                "CoreImage",
                "-o",
                str(executable),
            ],
            check=True,
        )
        subprocess.run([str(executable)], check=True)
