"""Compare incoming housekeeping and receive handoff against the recorded baseline.

Run from bridge/ with PYTHONPATH=src using its development Python environment.
Only temporary local files are used; no listeners, cameras or Printers are started.
"""

from __future__ import annotations

import ast
import asyncio
import fcntl
import json
import logging
import os
import platform
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from instantlink_bridge.camera import ftp
from instantlink_bridge.config import FtpConfig

BASELINE = "f5ed2c8"
ROUNDS = 20
OPERATIONS = 30


async def main(source: str) -> None:
    definition = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "prune_incoming_dir"
    )
    namespace = dict(vars(ftp))
    exec(compile(ast.Module(body=[definition], type_ignores=[]), "baseline", "exec"), namespace)
    variants = {"before": namespace["prune_incoming_dir"], "after": ftp.prune_incoming_dir}
    logging.disable(logging.CRITICAL)
    results = []
    with tempfile.TemporaryDirectory(prefix="instantlink-ftp-benchmark-") as temp:
        for count, size in ((8, 4 * 1024**2), (100, 2 * 1024**2), (1000, 256 * 1024)):
            incoming = Path(temp) / str(count) / "incoming"
            incoming.mkdir(parents=True)
            stamp = time.time() - 86400
            for index in range(count):
                path = incoming / f"DSC{index:05}.JPG"
                with path.open("wb") as output:
                    output.truncate(size)
                os.utime(path, (stamp + index, stamp + index))
            queue: asyncio.Queue[ftp.ReceivedImage] = asyncio.Queue(maxsize=100)
            service = ftp.FtpReceiveService(
                FtpConfig(incoming_dir=incoming),
                queue,
                asyncio.get_running_loop(),
                active_peer_host_provider=lambda: (),
            )
            protected = [incoming / f"DSC{index:05}.JPG" for index in range(3)]
            for path in protected:
                service._pin_received_image(path)
            received = incoming / f"DSC{count - 1:05}.JPG"
            lookup_counts = {}
            for name, prune in variants.items():
                with patch.object(os, "stat", wraps=os.stat) as stat_call:
                    assert prune(incoming, budget_bytes=512 * 1024**2) == []
                    lookup_counts[name] = stat_call.call_count
            for mode in ("prune", "receive_to_queue"):
                samples: dict[str, list[tuple[float, float]]] = {name: [] for name in variants}
                for trial in range(ROUNDS + 2):
                    # Two warm-up rounds, then alternating AB/BA trials.
                    order = list(variants) if trial % 2 == 0 else list(reversed(variants))
                    for name in order:
                        ftp.prune_incoming_dir = variants[name]
                        wall_start, cpu_start = time.perf_counter_ns(), time.process_time_ns()
                        for _ in range(OPERATIONS):
                            if mode == "prune":
                                removed = ftp.prune_incoming_dir(
                                    incoming,
                                    budget_bytes=512 * 1024**2,
                                    protected_paths=protected,
                                )
                                assert removed == []
                            else:
                                service._handle_received_file(str(received), "192.168.8.10")
                                await asyncio.sleep(0)
                                item = queue.get_nowait()
                                assert item.path == received
                                assert service.release_received_image(item.path)
                        wall = (time.perf_counter_ns() - wall_start) / OPERATIONS / 1e6
                        cpu = (time.process_time_ns() - cpu_start) / OPERATIONS / 1e6
                        if trial >= 2:
                            samples[name].append((wall, cpu))
                results.append(
                    {
                        "mode": mode,
                        "files": count,
                        "bytes_per_file": size,
                        "stat_calls_per_sweep": lookup_counts,
                        "samples_ms": samples,
                        "median_ms": {
                            name: {
                                "wall": statistics.median(wall for wall, _ in values),
                                "cpu": statistics.median(cpu for _, cpu in values),
                            }
                            for name, values in samples.items()
                        },
                    }
                )
    ftp.prune_incoming_dir = variants["after"]
    print(
        json.dumps(
            {
                "baseline": BASELINE,
                "platform": platform.platform(),
                "python": platform.python_version(),
                "rounds": ROUNDS,
                "operations_per_round": OPERATIONS,
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    source = subprocess.check_output(
        ["git", "show", f"{BASELINE}:bridge/src/instantlink_bridge/camera/ftp.py"], text=True
    )
    with Path("/tmp/instantlink-099-benchmark.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        asyncio.run(main(source))
