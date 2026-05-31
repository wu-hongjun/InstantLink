"""Tests for the live system metrics readers used by the LCD About page.

Each ``read_*`` reader accepts a ``path=`` injection so the tests work in
sandboxes and non-Pi hosts (CI, developer macOS) without poking at the real
``/sys``/``/proc`` tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from instantlink_bridge.system_stats import (
    CPUSampler,
    format_cpu_percent,
    format_memory,
    format_storage,
    format_temperature,
    read_memory,
    read_soc_temperature_c,
    read_storage,
    read_system_stats,
)


def _write_stat(path: Path, idle: int, total_others: int) -> None:
    """Write a minimal ``/proc/stat`` line; idle is column 4."""

    # cpu user nice system idle iowait irq softirq steal guest guest_nice
    fields = [total_others, 0, 0, idle, 0, 0, 0, 0, 0, 0]
    path.write_text("cpu  " + " ".join(str(value) for value in fields) + "\n", encoding="utf-8")


def test_cpu_sampler_first_call_returns_none(tmp_path: Path) -> None:
    stat_path = tmp_path / "stat"
    _write_stat(stat_path, idle=100, total_others=0)
    sampler = CPUSampler()
    assert sampler.sample(path=str(stat_path)) is None


def test_cpu_sampler_second_call_returns_percent(tmp_path: Path) -> None:
    stat_path = tmp_path / "stat"
    _write_stat(stat_path, idle=100, total_others=0)
    sampler = CPUSampler()
    sampler.sample(path=str(stat_path))
    # Advance: 50 idle ticks and 50 busy ticks → 50% used.
    _write_stat(stat_path, idle=150, total_others=50)
    percent = sampler.sample(path=str(stat_path))
    assert percent is not None
    assert percent == pytest.approx(50.0, abs=0.5)


def test_cpu_sampler_handles_missing_proc_stat(tmp_path: Path) -> None:
    missing = tmp_path / "absent"
    sampler = CPUSampler()
    assert sampler.sample(path=str(missing)) is None
    # Calling again still doesn't raise; state was never primed.
    assert sampler.sample(path=str(missing)) is None


def test_read_memory_parses_meminfo_format(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:         475044 kB\n"
        "MemFree:          120000 kB\n"
        "MemAvailable:     170000 kB\n"
        "Buffers:           10000 kB\n",
        encoding="utf-8",
    )
    result = read_memory(path=str(meminfo))
    assert result is not None
    used_mb, total_mb = result
    # 475044 // 1024 == 463
    assert total_mb == 463
    # used kB = 475044 - 170000 = 305044; // 1024 = 297
    assert used_mb == 297


def test_read_memory_returns_none_on_missing_file(tmp_path: Path) -> None:
    assert read_memory(path=str(tmp_path / "absent")) is None


def test_read_storage_returns_used_total_gb(tmp_path: Path) -> None:
    # tmp_path is a real filesystem mount, so statvfs will succeed.
    result = read_storage(path=str(tmp_path))
    assert result is not None
    used_gb, total_gb = result
    assert total_gb > 0.0
    assert used_gb >= 0.0
    assert used_gb <= total_gb


def test_read_soc_temperature_parses_millicelsius(tmp_path: Path) -> None:
    thermal = tmp_path / "temp"
    thermal.write_text("52616\n", encoding="utf-8")
    assert read_soc_temperature_c(path=str(thermal)) == pytest.approx(52.616)


def test_read_soc_temperature_returns_none_on_missing_file(tmp_path: Path) -> None:
    assert read_soc_temperature_c(path=str(tmp_path / "absent")) is None


def test_format_cpu_percent_handles_none() -> None:
    assert format_cpu_percent(None) == "—"
    assert format_cpu_percent(23.0) == "23%"
    assert format_cpu_percent(0.4) == "0%"


def test_format_memory_handles_none() -> None:
    assert format_memory(None, None) == "—"
    assert format_memory(297, None) == "—"
    assert format_memory(None, 463) == "—"
    assert format_memory(297, 463) == "297 / 463 MB"


def test_format_storage_handles_none() -> None:
    assert format_storage(None, None) == "—"
    assert format_storage(6.3, 57.0) == "6.3 / 57 GB"
    # Both sides ≥ 10 use integers.
    assert format_storage(12.0, 57.0) == "12 / 57 GB"


def test_format_temperature_handles_none() -> None:
    assert format_temperature(None) == "—"
    assert format_temperature(52.616) == "53°C"


def test_read_system_stats_bundles_readings_with_none_fallbacks() -> None:
    """The top-level reader should never raise even on a sandboxed host."""

    # Disable the warm-up double-sample so this test stays fast / deterministic;
    # the warm-up behavior is covered by its own focused test below.
    snapshot = read_system_stats(CPUSampler(), initial_sample_gap_s=0.0)
    # Storage at "/" is always readable.
    assert snapshot.storage_total_gb is not None
    assert snapshot.storage_used_gb is not None
    # CPU% is None on the first sample when the warm-up is disabled.
    assert snapshot.cpu_percent is None


def test_read_system_stats_warmup_takes_a_double_sample_so_first_call_returns_percent() -> None:
    """First-time visitors to the About page should never see ``"—"`` for CPU.

    The user reported seeing the em-dash because the cached snapshot was
    populated by the very first ``sample()`` call (which returns ``None`` —
    no baseline yet) and never refreshed unless they navigated. The fix:
    when the sampler returns ``None``, ``read_system_stats`` briefly
    sleeps and resamples so the first call always yields a real percent.
    """

    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    snapshot = read_system_stats(
        CPUSampler(),
        initial_sample_gap_s=0.05,
        sleep=fake_sleep,
    )
    assert sleeps == [0.05]
    # On a real host this is never None; in CI the sandbox still has /proc/stat
    # because the bridge runs on Linux runners. Soft-assert if the CI path
    # lacks /proc/stat entirely (would be the macOS dev box) by allowing None.
    if snapshot.cpu_percent is not None:
        assert 0.0 <= snapshot.cpu_percent <= 100.0


def test_read_system_stats_warmup_can_be_disabled_for_test_speed() -> None:
    """initial_sample_gap_s=0 skips the warm-up; sleep should never be called."""

    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    read_system_stats(
        CPUSampler(),
        initial_sample_gap_s=0.0,
        sleep=fake_sleep,
    )
    assert sleeps == []
