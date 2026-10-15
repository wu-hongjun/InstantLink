"""Preserve file and ownership semantics while reducing retention comparison cost."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from instantlink_bridge.camera.ftp import prune_incoming_dir

NOW = 1_800_000_000.0


def photo(path: Path, *, age: float = 86400) -> Path:
    path.write_bytes(b"exact camera original\x00\xff")
    path.chmod(0o640)
    os.utime(path, (NOW - age, NOW - age))
    return path


def test_resolved_paths_preserve_ownership_through_directory_alias(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(incoming, target_is_directory=True)
    protected = photo(incoming / "protected.hif", age=30 * 86400)
    obsolete = photo(incoming / "obsolete.hif", age=31 * 86400)

    assert prune_incoming_dir(
        alias,
        budget_bytes=0,
        keep_newest=0,
        now=NOW,
        protected_paths=[alias / protected.name],
    ) == [obsolete]
    assert protected.read_bytes() == b"exact camera original\x00\xff"
    assert protected.stat().st_mode & 0o777 == 0o640


def test_symlink_files_follow_target_metadata_but_never_delete_target(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    target = photo(tmp_path / "original.hif", age=30 * 86400)
    link = incoming / "linked.hif"
    link.symlink_to(target)
    dangling = incoming / "dangling.hif"
    dangling.symlink_to(tmp_path / "missing.hif")
    directory_link = incoming / "directory"
    directory_link.symlink_to(tmp_path, target_is_directory=True)

    assert prune_incoming_dir(incoming, budget_bytes=0, now=NOW) == [link]
    assert target.read_bytes() == b"exact camera original\x00\xff"
    assert target.stat().st_mode & 0o777 == 0o640
    assert dangling.is_symlink()
    assert directory_link.is_symlink()


def test_symlink_metadata_is_fresh_after_type_filtering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    target = photo(tmp_path / "original.hif", age=30 * 86400)
    link = incoming / "linked.hif"
    link.symlink_to(target)
    original_is_file = Path.is_file

    def updated_is_file(path: Path) -> bool:
        result = original_is_file(path)
        if path == link:
            # A resumed upload refreshes after the initial type check.
            os.utime(target, (NOW, NOW))
        return result

    monkeypatch.setattr(Path, "is_file", updated_is_file)
    assert prune_incoming_dir(incoming, budget_bytes=0, keep_newest=0, now=NOW) == []
    assert (incoming / "linked.hif").is_symlink()


def test_symlink_loop_is_ignored_without_aborting_retention(tmp_path: Path) -> None:
    loop = tmp_path / "loop.hif"
    loop.symlink_to(loop)
    obsolete = photo(tmp_path / "obsolete.jpg", age=30 * 86400)
    assert prune_incoming_dir(tmp_path, budget_bytes=0, now=NOW) == [obsolete]
    assert loop.is_symlink()


def test_protection_normalizes_relative_spelling_without_folding_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    original = photo(incoming / "Camera.JPG", age=30 * 86400)
    monkeypatch.chdir(tmp_path)
    assert (
        prune_incoming_dir(
            Path("incoming"),
            budget_bytes=0,
            keep_newest=0,
            now=NOW,
            protected_paths=[Path("incoming") / ".." / "incoming" / "Camera.JPG"],
        )
        == []
    )
    # Path equality on the Bridge is spelling-sensitive, including on a Mac
    # filesystem that happens to resolve these different spellings to one inode.
    assert prune_incoming_dir(
        Path("incoming"),
        budget_bytes=0,
        keep_newest=0,
        now=NOW,
        protected_paths=[incoming / "CAMERA.JPG"],
    ) == [original]


def test_same_mtime_uses_scan_order_for_budget_and_newest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = [photo(tmp_path / f"photo-{index}.jpg") for index in range(3)]
    order = [paths[2], paths[0], paths[1]]

    def ordered_iterdir(path: Path) -> Iterator[Path]:
        assert path == tmp_path
        return iter(order)

    monkeypatch.setattr(Path, "iterdir", ordered_iterdir)
    assert prune_incoming_dir(tmp_path, budget_bytes=0, keep_newest=1, now=NOW) == order[:2]
    assert order[-1].exists()


def test_missing_file_between_scan_and_stat_does_not_abort_other_retirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vanished = photo(tmp_path / "vanished.jpg")
    obsolete = photo(tmp_path / "obsolete.jpg")
    original_is_file = Path.is_file

    def changing_is_file(path: Path) -> bool:
        result = original_is_file(path)
        if path == vanished:
            vanished.unlink()
        return result

    monkeypatch.setattr(Path, "is_file", changing_is_file)
    assert prune_incoming_dir(tmp_path, budget_bytes=0, keep_newest=0, now=NOW) == [obsolete]


def test_scan_failure_does_not_retire_partial_candidate_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    original = photo(tmp_path / "original.jpg", age=30 * 86400)

    def failing_iterdir(path: Path) -> Iterator[Path]:
        assert path == tmp_path
        yield original
        raise OSError("directory read failed")

    monkeypatch.setattr(Path, "iterdir", failing_iterdir)
    assert prune_incoming_dir(tmp_path, budget_bytes=0, keep_newest=0, now=NOW) == []
    assert original.exists()
    assert "ftp.incoming_prune_scan_failed" in caplog.text


def test_type_check_permission_failure_aborts_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    blocked = photo(tmp_path / "blocked.jpg", age=30 * 86400)
    other = photo(tmp_path / "other.jpg", age=30 * 86400)
    original_is_file = Path.is_file

    def denied_is_file(path: Path) -> bool:
        if path == blocked:
            raise PermissionError("type lookup denied")
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", denied_is_file)
    assert prune_incoming_dir(tmp_path, budget_bytes=0, now=NOW) == []
    assert blocked.exists() and other.exists()
    assert "ftp.incoming_prune_scan_failed" in caplog.text


def test_second_stat_permission_failure_skips_only_that_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked = photo(tmp_path / "blocked.jpg", age=30 * 86400)
    other = photo(tmp_path / "other.jpg", age=30 * 86400)
    original_stat = Path.stat
    calls = 0

    def denied_second_stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        nonlocal calls
        if path == blocked:
            calls += 1
            if calls == 2:
                raise PermissionError("metadata lookup denied")
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", denied_second_stat)
    assert prune_incoming_dir(tmp_path, budget_bytes=0, now=NOW) == [other]
    assert blocked.read_bytes() == b"exact camera original\x00\xff"


def test_unlink_failure_retains_its_bytes_in_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked = photo(tmp_path / "blocked.jpg", age=2 * 86400)
    other = photo(tmp_path / "other.jpg")
    original_unlink = Path.unlink

    def deny_one(path: Path, missing_ok: bool = False) -> None:
        if path == blocked:
            raise PermissionError("file busy")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", deny_one)
    assert prune_incoming_dir(
        tmp_path, budget_bytes=blocked.stat().st_size, keep_newest=0, now=NOW
    ) == [other]
    assert blocked.read_bytes() == b"exact camera original\x00\xff"


def test_repeated_sweeps_refresh_file_size_and_mtime(tmp_path: Path) -> None:
    original = photo(tmp_path / "original.jpg")
    assert prune_incoming_dir(tmp_path, budget_bytes=128, keep_newest=0, now=NOW) == []
    original.write_bytes(b"replacement" * 32)
    os.utime(original, (NOW - 86400, NOW - 86400))
    assert prune_incoming_dir(tmp_path, budget_bytes=128, keep_newest=0, now=NOW) == [original]
