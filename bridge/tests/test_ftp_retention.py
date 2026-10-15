from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from instantlink_bridge.camera.ftp import FtpReceiveService, ReceivedImage
from instantlink_bridge.config import FtpConfig


def old_photo(directory: Path, name: str, *, age_s: float = 30 * 86400) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"photo")
    old = time.time() - age_s
    os.utime(path, (old, old))
    return path


@pytest.mark.asyncio
async def test_old_queued_and_active_photos_survive_new_upload_then_become_prunable(
    tmp_path: Path,
) -> None:
    incoming = tmp_path / "incoming"
    queue: asyncio.Queue[ReceivedImage] = asyncio.Queue(maxsize=100)
    service = FtpReceiveService(FtpConfig(incoming_dir=incoming), queue, asyncio.get_running_loop())
    queued = old_photo(incoming, "queued.hif")
    service._handle_received_file(str(queued), "192.168.8.10")
    await asyncio.sleep(0)
    assert (await queue.get()).path == queued
    # Dequeue moves this photo into active manual review; ownership continues.
    for index in range(10):
        latest = old_photo(incoming, f"new-{index}.hif", age_s=0)
        service._handle_received_file(str(latest), "192.168.8.10")
        await asyncio.sleep(0)
    service._prune_incoming()
    assert queued.exists(), (
        "active review source must survive after grace/newest protection expires"
    )
    assert service.release_received_image(queued)
    service._prune_incoming()
    assert not queued.exists()


@pytest.mark.asyncio
async def test_overflow_releases_rejected_photo_pin_and_keeps_accepted_photo(
    tmp_path: Path,
) -> None:
    incoming = tmp_path / "incoming"
    queue: asyncio.Queue[ReceivedImage] = asyncio.Queue(maxsize=1)
    service = FtpReceiveService(FtpConfig(incoming_dir=incoming), queue, asyncio.get_running_loop())
    accepted = old_photo(incoming, "accepted.hif")
    service._handle_received_file(str(accepted), "192.168.8.10")
    await asyncio.sleep(0)
    rejected = old_photo(incoming, "rejected.hif")
    service._handle_received_file(str(rejected), "192.168.8.10")
    await asyncio.sleep(0)
    assert accepted.exists()
    assert not rejected.exists()
    assert rejected.resolve() not in service._pending_paths
    assert service.release_received_image(accepted)
    assert service._pending_paths == {}


def test_shared_source_pin_is_released_only_after_all_accepted_jobs(tmp_path: Path) -> None:
    path = old_photo(tmp_path / "incoming", "same.hif")
    loop = asyncio.new_event_loop()
    try:
        service = FtpReceiveService(FtpConfig(incoming_dir=path.parent), asyncio.Queue(), loop)
        service._pin_received_image(path)
        service._pin_received_image(path)
        assert not service.release_received_image(path)
        service._prune_incoming()
        assert path.exists()
        assert service.release_received_image(path)
        service._prune_incoming()
        assert not path.exists()
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_overflow_does_not_unlink_a_source_owned_by_an_accepted_job(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    queue: asyncio.Queue[ReceivedImage] = asyncio.Queue(maxsize=1)
    service = FtpReceiveService(FtpConfig(incoming_dir=incoming), queue, asyncio.get_running_loop())
    path = old_photo(incoming, "shared.hif")
    service._handle_received_file(str(path), "192.168.8.10")
    await asyncio.sleep(0)
    service._handle_received_file(str(path), "192.168.8.10")
    await asyncio.sleep(0)
    assert path.exists()
    assert service._pending_paths == {path.resolve(): 1}
    assert service.release_received_image(path)


def test_closed_loop_releases_handoff_pin_and_retains_original(tmp_path: Path) -> None:
    path = old_photo(tmp_path / "incoming", "closed.hif")
    loop = asyncio.new_event_loop()
    service = FtpReceiveService(FtpConfig(incoming_dir=path.parent), asyncio.Queue(), loop)
    service._pin_received_image(path)
    loop.close()
    service._handoff_received_image(path, "192.168.8.10")
    assert service._pending_paths == {}
    assert path.exists()


@pytest.mark.asyncio
async def test_stop_before_callback_releases_only_handoff_owner(tmp_path: Path) -> None:
    path = old_photo(tmp_path / "incoming", "held.hif")
    queue: asyncio.Queue[ReceivedImage] = asyncio.Queue()
    service = FtpReceiveService(
        FtpConfig(incoming_dir=path.parent), queue, asyncio.get_running_loop()
    )
    service._pin_received_image(path)  # Active manual review owns one reference.
    service._pin_received_image(path)  # A second handoff is pending.
    service._handoff_received_image(path, "192.168.8.10")
    service.stop()
    await asyncio.sleep(0)
    assert queue.empty()
    assert service._pending_paths == {path.resolve(): 1}
    assert path.exists()
    service.release_received_image(path)
    assert not service._pending_paths


def test_completed_upload_after_stop_remains_on_disk_without_prune(tmp_path: Path) -> None:
    path = old_photo(tmp_path / "incoming", "late.hif")
    loop = asyncio.new_event_loop()
    try:
        service = FtpReceiveService(FtpConfig(incoming_dir=path.parent), asyncio.Queue(), loop)
        service.stop()
        service._handle_received_file(str(path), "192.168.8.10")
        assert path.exists()
        assert not service._pending_paths
    finally:
        loop.close()


def test_inflight_upload_survives_pruning_and_only_its_owner_can_release(tmp_path: Path) -> None:
    path = old_photo(tmp_path / "incoming", "upload.hif")
    loop = asyncio.new_event_loop()
    try:
        service = FtpReceiveService(FtpConfig(incoming_dir=path.parent), asyncio.Queue(), loop)
        owner, other = object(), object()
        assert service._reserve_upload(path, owner)
        assert not service._reserve_upload(path, other)
        service._release_upload(path, other)
        service._prune_incoming()
        assert path.exists()
        service._release_upload(path, owner)
        service._prune_incoming()
        assert not path.exists()
    finally:
        loop.close()
