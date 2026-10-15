"""Measure exact hue implementations from the Bridge development environment.

PYTHONPATH=bridge/src python docs/assets/performance-audit-099/07-bridge-postprocess-benchmark.py

Use --tile-sweep to reproduce the tile size exploration. pytest is required to
load the frozen reference from the regression test. Setup is outside timing.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import platform
import resource
import runpy
import statistics
import subprocess
import sys
import time
import tracemalloc
from collections.abc import Callable
from functools import partial
from pathlib import Path

import numpy as np
import PIL
from instantlink_bridge.imaging.postprocess import _apply_hue, _apply_hue_tile
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
reference: Callable[[Image.Image, int], Image.Image] = runpy.run_path(
    str(ROOT / "bridge/tests/test_postprocess_hue_equivalence.py")
)["_reference_hue"]


def tiled(image: Image.Image, degrees: int, size: tuple[int, int]) -> Image.Image:
    """Explore different tile sizes with the same exact pointwise helper."""
    width, height = image.size
    tile_width, tile_height = size
    if width <= tile_width and height <= tile_height:
        return _apply_hue_tile(image, degrees)
    result = Image.new("RGB", image.size)
    for top in range(0, height, tile_height):
        for left in range(0, width, tile_width):
            box = (left, top, min(left + tile_width, width), min(top + tile_height, height))
            result.paste(_apply_hue_tile(image.crop(box), degrees), (left, top))
    return result


def peak_rss_bytes() -> int:
    """Normalize macOS bytes / Linux KiB for this benchmark's supported hosts."""
    maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return maximum if sys.platform == "darwin" else maximum * 1024


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tile-sweep", action="store_true")
    parser.add_argument("--rss-worker", choices=["before", "untiled_candidate", "after"])
    args = parser.parse_args()
    functions: dict[str, Callable[[Image.Image, int], Image.Image]] = {
        "before": reference,
        "untiled_candidate": _apply_hue_tile,
        "after": _apply_hue,
    }
    rng = np.random.default_rng(9917)
    if args.rss_worker:
        image = Image.fromarray(rng.integers(0, 256, size=(2309, 3464, 3), dtype=np.uint8))
        setup_peak = peak_rss_bytes()
        functions[args.rss_worker](image, 17)
        print(json.dumps({"setup_peak_rss_bytes": setup_peak, "peak_rss_bytes": peak_rss_bytes()}))
        return
    if args.tile_sweep:
        functions = {"untiled_candidate": _apply_hue_tile}
        for size in [(256, 256), (512, 256), (512, 512), (1024, 256)]:
            functions[str(size)] = partial(tiled, size=size)
    sizes = (
        [(3464, 2309)] if args.tile_sweep else [(88, 88), (600, 800), (1600, 1200), (3464, 2309)]
    )
    images = {
        f"{width}x{height}": Image.fromarray(
            rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
        )
        for width, height in sizes
    }
    result: dict[str, object] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version,
        "numpy": np.__version__,
        "pillow": PIL.__version__,
        "degrees": 17,
        "repeats": 12,
        "timing": "rotating/reversing variant order; two warmups; imports/fixtures excluded",
        "memory": "tracemalloc peak during one call, excludes fixture/native Pillow allocations",
        "rss": "fresh child per variant at 3464x2309; includes imports/input/native allocations",
    }
    cases: dict[str, object] = {}
    with Path("/tmp/instantlink-099-benchmark.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for label, image in images.items():
            expected = reference(image, 17).tobytes()
            for function in functions.values():
                assert function(image, 17).tobytes() == expected
                for _ in range(2):
                    function(image, 17)
            del expected
            wall: dict[str, list[float]] = {name: [] for name in functions}
            cpu: dict[str, list[float]] = {name: [] for name in functions}
            for sample in range(12):
                names = list(functions)
                offset = (sample // 2) % len(names)
                order = names[offset:] + names[:offset]
                if sample % 2:
                    order.reverse()
                for name in order:
                    wall_start, cpu_start = time.perf_counter(), time.process_time()
                    functions[name](image, 17)
                    cpu[name].append((time.process_time() - cpu_start) * 1000)
                    wall[name].append((time.perf_counter() - wall_start) * 1000)
            case: dict[str, object] = {}
            for name, function in functions.items():
                tracemalloc.start()
                function(image, 17)
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                case[name] = {
                    "wall_ms_samples": wall[name],
                    "wall_ms_median": statistics.median(wall[name]),
                    "wall_ms_range": [min(wall[name]), max(wall[name])],
                    "cpu_ms_samples": cpu[name],
                    "cpu_ms_median": statistics.median(cpu[name]),
                    "peak_traced_bytes": peak,
                }
            cases[label] = case
        if not args.tile_sweep:
            result["fresh_child_rss"] = {
                name: json.loads(
                    subprocess.check_output(
                        [sys.executable, str(Path(__file__).resolve()), "--rss-worker", name],
                        text=True,
                        timeout=60,
                    )
                )
                for name in functions
            }
        fcntl.flock(lock, fcntl.LOCK_UN)
    result["cases"] = cases
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
