"""Measure only the completed support ZIP hashing stage, with warm filesystem cache.

Run with the Bridge Python environment. ZIP fixture generation is outside the
shared timing lock; timings and tracemalloc peaks are measured in separate passes.
The candidate is the actual production helper; the baseline is its former code.
"""

from __future__ import annotations

import fcntl
import gc
import hashlib
import json
import platform
import random
import statistics
import sys
import tempfile
import time
import tracemalloc
import zipfile
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "bridge" / "src"))

from instantlink_bridge.manager.diagnostics import _file_sha256  # noqa: E402

LOCK = Path("/tmp/instantlink-099-benchmark.lock")
SAMPLES = 7


def baseline(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_archive(path: Path, text_bytes: int) -> None:
    rng = random.Random(99)
    block = b"".join(
        b"2026-10-15T05:00:00Z INFO bridge.camera upload_complete transfer_id="
        + rng.randbytes(32).hex().encode()
        + b" bytes=4194304 elapsed_ms=307\n"
        for _ in range(4096)
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", '{"schema_version":1}')
        with archive.open("var/log/instantlink-bridge.log", "w") as log:
            remaining = text_bytes
            while remaining:
                chunk = block[:remaining]
                log.write(chunk)
                remaining -= len(chunk)


def measure_time(fn: Callable[[Path], str], path: Path, iterations: int) -> tuple[float, float]:
    cpu_start = time.process_time_ns()
    wall_start = time.perf_counter_ns()
    for _ in range(iterations):
        fn(path)
    wall_ms = (time.perf_counter_ns() - wall_start) / 1_000_000 / iterations
    cpu_ms = (time.process_time_ns() - cpu_start) / 1_000_000 / iterations
    return wall_ms, cpu_ms


def measure_peak(fn: Callable[[Path], str], path: Path) -> int:
    gc.collect()
    tracemalloc.start()
    try:
        fn(path)
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def summary(samples: list[float] | list[int]) -> dict[str, float]:
    return {"median": statistics.median(samples), "min": min(samples), "max": max(samples)}


def run() -> None:
    results: dict[str, object] = {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "samples_per_variant": SAMPLES,
        "lock": str(LOCK),
        "method": "alternating paired order; three warmups; warm cache; hash stage only",
        "memory": "peak traced Python allocations per hash, separate from timing; excludes RSS",
        "fixture": "deterministic synthetic event logs in closed DEFLATED ZIPs",
    }
    cases: list[dict[str, object]] = []
    functions = {"baseline": baseline, "candidate": _file_sha256}
    with tempfile.TemporaryDirectory(prefix="instantlink-diagnostics-benchmark-") as temporary:
        fixtures = []
        for text_bytes in (65536, 4 * 1048576, 128 * 1048576):
            path = Path(temporary) / f"log-{text_bytes}.zip"
            make_archive(path, text_bytes)
            fixtures.append((text_bytes, path))
        with LOCK.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            results["measurement_started_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            for text_bytes, path in fixtures:
                expected = baseline(path)
                for _ in range(3):
                    assert baseline(path) == _file_sha256(path) == expected
                calibration_ms, _ = measure_time(baseline, path, 5)
                iterations = max(1, min(10000, int(400 / calibration_ms)))
                wall: dict[str, list[float]] = {name: [] for name in functions}
                cpu: dict[str, list[float]] = {name: [] for name in functions}
                peaks: dict[str, list[int]] = {name: [] for name in functions}
                for sample in range(SAMPLES):
                    names = list(functions)
                    if sample % 2:
                        names.reverse()
                    for name in names:
                        wall_ms, cpu_ms = measure_time(functions[name], path, iterations)
                        wall[name].append(wall_ms)
                        cpu[name].append(cpu_ms)
                for sample in range(SAMPLES):
                    names = list(functions)
                    if sample % 2:
                        names.reverse()
                    for name in names:
                        peaks[name].append(measure_peak(functions[name], path))
                cases.append(
                    {
                        "log_text_bytes": text_bytes,
                        "zip_bytes": path.stat().st_size,
                        "sha256": expected,
                        "iterations_per_sample": iterations,
                        "wall_ms_samples": wall,
                        "cpu_ms_samples": cpu,
                        "peak_traced_bytes_samples": peaks,
                        "wall_ms_summary": {name: summary(values) for name, values in wall.items()},
                        "cpu_ms_summary": {name: summary(values) for name, values in cpu.items()},
                        "peak_traced_bytes_summary": {
                            name: summary(values) for name, values in peaks.items()
                        },
                    }
                )
            results["measurement_finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results["cases"] = cases
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    run()
