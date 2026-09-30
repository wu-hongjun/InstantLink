#!/usr/bin/env python3
"""Record low-overhead Bridge activity during a battery runtime test.

The X306 has no host-readable current or charge gauge. This records uptime and
workload once per interval so the last durable sample after a battery cutoff
bounds runtime to within one interval. It does not report watts or charge state.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return None


def _read_int(path: Path) -> int | None:
    value = _read(path)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _cpu_ticks() -> tuple[int, int]:
    fields = (_read(Path("/proc/stat")) or "").splitlines()[0].split()[1:]
    ticks = [int(value) for value in fields]
    return sum(ticks), ticks[3] + ticks[4]


def _process_ticks() -> dict[int, tuple[str, int]]:
    processes: dict[int, tuple[str, int]] = {}
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        value = _read(path / "stat")
        if value is None:
            continue
        try:
            name = value.split("(", 1)[1].rsplit(")", 1)[0]
            fields = value.rsplit(")", 1)[1].split()
            processes[int(path.name)] = (name, int(fields[11]) + int(fields[12]))
        except (IndexError, ValueError):
            continue
    return processes


def _memory() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in (_read(Path("/proc/meminfo")) or "").splitlines():
        name, _, value = line.partition(":")
        if name in {"MemAvailable", "SwapTotal", "SwapFree"}:
            values[name] = int(value.strip().split()[0])
    return values


def _throttled_flags() -> int | None:
    """Read Pi undervoltage/throttling flags, including sticky per-boot history."""

    try:
        result = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    prefix, _, value = result.stdout.strip().partition("=")
    if prefix != "throttled":
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def _snapshot(
    previous: tuple[float, tuple[int, int], dict[int, tuple[str, int]]] | None,
) -> tuple[dict[str, Any], tuple[float, tuple[int, int], dict[int, tuple[str, int]]]]:
    now = time.monotonic()
    cpu = _cpu_ticks()
    processes = _process_ticks()
    sample: dict[str, Any] = {
        "wall_time": datetime.now().astimezone().isoformat(),
        "boot_id": _read(Path("/proc/sys/kernel/random/boot_id")),
        "uptime_s": round(float((_read(Path("/proc/uptime")) or "0").split()[0]), 1),
        "temperature_c": (_read_int(Path("/sys/class/thermal/thermal_zone0/temp")) or 0) / 1000,
        "cpu_mhz": (_read_int(Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")) or 0)
        / 1000,
        "cpu_governor": _read(Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")),
        "memory_kb": _memory(),
        "throttled_flags": _throttled_flags(),
        "backlight_power": next(
            (_read(path) for path in Path("/sys/class/backlight").glob("*/bl_power")), None
        ),
        "wlan0_rx_bytes": _read_int(Path("/sys/class/net/wlan0/statistics/rx_bytes")),
        "wlan0_tx_bytes": _read_int(Path("/sys/class/net/wlan0/statistics/tx_bytes")),
        "usb0_carrier": _read_int(Path("/sys/class/net/usb0/carrier")),
    }
    if previous is not None:
        then, old_cpu, old_processes = previous
        elapsed = now - then
        total_delta = cpu[0] - old_cpu[0]
        idle_delta = cpu[1] - old_cpu[1]
        sample["cpu_busy_percent"] = (
            round(100 * (total_delta - idle_delta) / total_delta, 1) if total_delta > 0 else None
        )
        clock_ticks = os.sysconf("SC_CLK_TCK")
        activity = []
        for pid, (name, ticks) in processes.items():
            earlier = old_processes.get(pid)
            if earlier is None or earlier[0] != name:
                continue
            percent = 100 * (ticks - earlier[1]) / (clock_ticks * elapsed)
            if percent >= 0.1:
                activity.append(
                    {"pid": pid, "name": name, "cpu_percent_of_core": round(percent, 1)}
                )
        sample["top_processes"] = sorted(
            activity, key=lambda item: item["cpu_percent_of_core"], reverse=True
        )[:8]
    return sample, (now, cpu, processes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=60, help="seconds between samples")
    parser.add_argument("--samples", type=int, default=0, help="0 records until stopped")
    parser.add_argument("--output", type=Path, help="append JSONL here and fsync each sample")
    args = parser.parse_args()
    if args.interval <= 0 or args.samples < 0:
        parser.error("interval must be positive and samples must be nonnegative")
    previous = None
    count = 0
    while args.samples == 0 or count < args.samples:
        sample, previous = _snapshot(previous)
        line = json.dumps(sample, separators=(",", ":")) + "\n"
        if args.output is None:
            print(line, end="", flush=True)
        else:
            with args.output.open("a", encoding="utf-8") as output:
                output.write(line)
                output.flush()
                os.fsync(output.fileno())
        count += 1
        if args.samples == 0 or count < args.samples:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
