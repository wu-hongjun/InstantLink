"""Compare the original asdict index writer with the production scalar writer.

Run from the repository root with the Bridge Python environment. Fixture setup,
imports, equivalence checks, and warmups are outside timing. No photo copying or
hashing is measured; publication includes JSON encoding, file write, and replace.
"""

from __future__ import annotations

import fcntl
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "bridge" / "src"))

from instantlink_bridge.sync.models import OutboxItem  # noqa: E402
from instantlink_bridge.sync.outbox import (  # noqa: E402
    INDEX_FILE_NAME,
    INDEX_VERSION,
    LOGGER,
    SyncOutbox,
)


class BaselineOutbox(SyncOutbox):
    """Original _write_index_locked implementation, including failure cleanup."""

    def _write_index_locked(self, proposed: dict[str, OutboxItem]) -> None:
        payload = {
            "version": INDEX_VERSION,
            "items": [asdict(item) for item in proposed.values()],
        }
        index_path = self._root / INDEX_FILE_NAME
        tmp_path = self._root / f"{INDEX_FILE_NAME}.tmp"
        try:
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp_path, index_path)
        except BaseException:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("sync.outbox_index_temp_unlink_failed", exc_info=True)
            raise


def run() -> None:
    result: dict[str, object] = {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "samples_per_variant": 15,
        "units": "milliseconds per full index publication",
        "lock": "/tmp/instantlink-099-benchmark.lock",
        "method": "alternating baseline/candidate order; 3 warmups; no fsync (same as production)",
    }
    cases = []
    with tempfile.TemporaryDirectory(prefix="instantlink-outbox-benchmark-") as temporary:
        base_root = Path(temporary) / "baseline"
        candidate_root = Path(temporary) / "candidate"
        baseline = BaselineOutbox(base_root, budget_mb=64)
        candidate = SyncOutbox(candidate_root, budget_mb=64)
        # Preconstruct fixtures before taking the shared benchmark lock.
        fixtures = {
            depth: {
                f"{i:016x}": OutboxItem(
                    item_id=f"{i:016x}",
                    file_name=f"DSC{i:05d}.JPG",
                    size_bytes=4 * 1024 * 1024,
                    sha256=f"{i:064x}",
                    received_at=1_734_424_552.125 + i,
                    source_remote_ip="192.168.8.20",
                )
                for i in range(depth)
            }
            for depth in [1, 64, 1024]
        }
        with Path(str(result["lock"])).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for depth, items in fixtures.items():
                iterations = {1: 100, 64: 30, 1024: 5}[depth]
                for _ in range(3):
                    baseline._write_index_locked(items)
                    candidate._write_index_locked(items)
                expected_bytes = (base_root / INDEX_FILE_NAME).read_bytes()
                assert (candidate_root / INDEX_FILE_NAME).read_bytes() == expected_bytes
                samples: dict[str, list[float]] = {"baseline": [], "candidate": []}
                writers = {
                    "baseline": baseline._write_index_locked,
                    "candidate": candidate._write_index_locked,
                }
                for sample in range(15):
                    order = ["baseline", "candidate"]
                    if sample % 2:
                        order.reverse()
                    for name in order:
                        start = time.perf_counter_ns()
                        for _ in range(iterations):
                            writers[name](items)
                        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000 / iterations
                        samples[name].append(elapsed_ms)
                baseline_ms = statistics.median(samples["baseline"])
                candidate_ms = statistics.median(samples["candidate"])
                cases.append(
                    {
                        "depth": depth,
                        "iterations_per_sample": iterations,
                        "index_bytes": len(expected_bytes),
                        "samples_ms": samples,
                        "baseline_median_ms": baseline_ms,
                        "candidate_median_ms": candidate_ms,
                        "baseline_range_ms": [
                            min(samples["baseline"]),
                            max(samples["baseline"]),
                        ],
                        "candidate_range_ms": [
                            min(samples["candidate"]),
                            max(samples["candidate"]),
                        ],
                        "median_reduction_percent": 100 * (1 - candidate_ms / baseline_ms),
                    }
                )
    result["cases"] = cases
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run()
