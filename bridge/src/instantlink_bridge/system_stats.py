"""Live system metrics for the LCD About page.

Cheap, pure-Python readers backed by ``/proc`` and ``/sys``. The readers each
return ``None`` on any IO/parse error rather than raising so the LCD can render
``"—"`` for missing values on non-Pi hosts (developer macOS / CI sandbox /
container without ``/sys`` access).

Why we don't reuse `pitop` (the user's TUI) here: pitop ships as a binary with
no JSON or library mode, so it can't be embedded. The reads we need are just a
handful of lines from ``/proc/stat``, ``/proc/meminfo``, ``os.statvfs`` and the
SoC thermal zone — rolling our own keeps the bridge dependency-free.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_STAT_PATH = "/proc/stat"
_DEFAULT_MEMINFO_PATH = "/proc/meminfo"
_DEFAULT_THERMAL_PATH = "/sys/class/thermal/thermal_zone0/temp"
_DEFAULT_STORAGE_PATH = "/"


@dataclass(frozen=True, slots=True)
class SystemStatsSnapshot:
    """Cheap-to-sample system metrics shown on the LCD About page."""

    cpu_percent: float | None
    """0..100, ``None`` when the CPU sampler hasn't seen two reads yet."""

    ram_used_mb: int | None
    ram_total_mb: int | None
    storage_used_gb: float | None
    storage_total_gb: float | None
    soc_temperature_c: float | None
    """Pi Zero 2 W shares one thermal zone between CPU and GPU."""


class CPUSampler:
    """Compute CPU usage by diffing two reads of ``/proc/stat``.

    ``/proc/stat`` exposes cumulative jiffies since boot for each CPU mode
    (user, nice, system, idle, iowait, irq, softirq, steal, guest,
    guest_nice). Usage % = ``1 - (delta_idle / delta_total)`` between two
    samples. The first ``sample()`` call returns ``None`` (no baseline yet);
    subsequent calls return the percentage since the previous call.
    """

    def __init__(self) -> None:
        self._last_total: int | None = None
        self._last_idle: int | None = None

    def sample(self, *, path: str = _DEFAULT_STAT_PATH) -> float | None:
        """Return CPU% since the previous sample, or ``None`` if unavailable."""

        try:
            with Path(path).open(encoding="utf-8") as handle:
                first_line = handle.readline()
        except OSError:
            return None
        parts = first_line.split()
        if not parts or parts[0] != "cpu" or len(parts) < 5:
            return None
        try:
            fields = [int(value) for value in parts[1:]]
        except ValueError:
            return None
        # idle + iowait counts as idle (Linux convention used by `top`).
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        total = sum(fields)
        last_total = self._last_total
        last_idle = self._last_idle
        self._last_total = total
        self._last_idle = idle
        if last_total is None or last_idle is None:
            return None
        delta_total = total - last_total
        delta_idle = idle - last_idle
        if delta_total <= 0:
            return None
        used = 1.0 - (delta_idle / delta_total)
        return max(0.0, min(100.0, used * 100.0))


def read_memory(*, path: str = _DEFAULT_MEMINFO_PATH) -> tuple[int, int] | None:
    """Return ``(used_mb, total_mb)`` parsed from ``/proc/meminfo``.

    Used = ``MemTotal - MemAvailable`` (matches what ``free -m`` reports as
    the "used" column on modern kernels). Returns ``None`` on any IO or
    parse failure.
    """

    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    total_kb: int | None = None
    available_kb: int | None = None
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            total_kb = _parse_meminfo_kb(line)
        elif line.startswith("MemAvailable:"):
            available_kb = _parse_meminfo_kb(line)
        if total_kb is not None and available_kb is not None:
            break
    if total_kb is None or available_kb is None:
        return None
    used_kb = max(0, total_kb - available_kb)
    return used_kb // 1024, total_kb // 1024


def _parse_meminfo_kb(line: str) -> int | None:
    """Parse ``Key:  12345 kB`` lines from /proc/meminfo."""

    parts = line.split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def read_storage(*, path: str = _DEFAULT_STORAGE_PATH) -> tuple[float, float] | None:
    """Return ``(used_gb, total_gb)`` for the filesystem at ``path``.

    Uses ``os.statvfs`` so this works on any POSIX host. Returns ``None``
    if the path doesn't exist or stat fails.
    """

    try:
        stats = os.statvfs(path)
    except OSError:
        return None
    block_size = stats.f_frsize or stats.f_bsize
    total_bytes = stats.f_blocks * block_size
    free_bytes = stats.f_bavail * block_size
    used_bytes = max(0, total_bytes - free_bytes)
    gb = 1024.0 * 1024.0 * 1024.0
    return used_bytes / gb, total_bytes / gb


def read_soc_temperature_c(*, path: str = _DEFAULT_THERMAL_PATH) -> float | None:
    """Return SoC temperature in °C from ``thermal_zone0``.

    The kernel exposes millicelsius (e.g. ``"52616"`` → 52.6°C). Returns
    ``None`` when the file is missing — non-Pi hosts (macOS dev box, CI)
    don't have this thermal zone.
    """

    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return int(raw) / 1000.0
    except ValueError:
        return None


_DEFAULT_INITIAL_SAMPLE_GAP_S = 0.1


def read_system_stats(
    cpu_sampler: CPUSampler,
    *,
    initial_sample_gap_s: float = _DEFAULT_INITIAL_SAMPLE_GAP_S,
    sleep: object = time.sleep,
) -> SystemStatsSnapshot:
    """Bundle the four live readings into a single snapshot.

    Every reader degrades to ``None`` on IO failure; callers render those
    as ``"—"`` via the ``format_*`` helpers below.

    First-call warm-up: ``CPUSampler.sample`` needs two reads of
    ``/proc/stat`` to compute a delta; the very first call against a fresh
    sampler has no baseline and returns ``None``. To avoid showing ``"—"``
    on the user's first visit to the About page, we take a baseline read,
    sleep ``initial_sample_gap_s`` (default 100 ms), and re-sample. The
    delta over that short window is a reasonable instantaneous reading
    and the brief block is only paid on the first call per sampler — the
    controller's 3-second snapshot cache covers the rest.

    ``sleep`` is injected so tests can avoid the real-time delay.
    """

    cpu_percent = cpu_sampler.sample()
    if cpu_percent is None and initial_sample_gap_s > 0.0:
        # Baseline established by the previous sample(); pause briefly so
        # /proc/stat advances, then resample to get a real percent.
        sleep(initial_sample_gap_s)  # type: ignore[operator]
        cpu_percent = cpu_sampler.sample()
    memory = read_memory()
    storage = read_storage()
    return SystemStatsSnapshot(
        cpu_percent=cpu_percent,
        ram_used_mb=memory[0] if memory is not None else None,
        ram_total_mb=memory[1] if memory is not None else None,
        storage_used_gb=storage[0] if storage is not None else None,
        storage_total_gb=storage[1] if storage is not None else None,
        soc_temperature_c=read_soc_temperature_c(),
    )


_MISSING = "—"  # Unicode em dash (U+2014).


def format_cpu_percent(percent: float | None) -> str:
    """Return a compact LCD label for CPU usage (e.g. ``"23%"``)."""

    if percent is None:
        return _MISSING
    return f"{round(percent)}%"


def format_memory(used_mb: int | None, total_mb: int | None) -> str:
    """Return ``"297 / 463 MB"`` or ``"—"`` if either side is missing."""

    if used_mb is None or total_mb is None:
        return _MISSING
    return f"{used_mb} / {total_mb} MB"


def format_storage(used_gb: float | None, total_gb: float | None) -> str:
    """Return ``"6.3 / 57 GB"`` or ``"—"`` if either side is missing.

    Uses one decimal for values under 10 GB and an integer otherwise, so
    the row reads cleanly on the 240px-wide LCD picker.
    """

    if used_gb is None or total_gb is None:
        return _MISSING
    return f"{_format_gb(used_gb)} / {_format_gb(total_gb)} GB"


def _format_gb(value: float) -> str:
    if value < 10.0:
        return f"{value:.1f}"
    return f"{round(value)}"


def format_temperature(celsius: float | None) -> str:
    """Return ``"53°C"`` or ``"—"`` if the thermal zone is unavailable."""

    if celsius is None:
        return _MISSING
    return f"{round(celsius)}°C"
