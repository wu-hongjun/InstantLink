from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Protocol

import pytest

from instantlink_bridge.camera.ftp import FtpReceiveService, ReceivedImage
from instantlink_bridge.config import FtpConfig


class TransferHandler(Protocol):
    replies: list[str]
    calls: list[tuple[str, str]]
    outcome: str

    def on_connect(self) -> None: ...
    def ftp_STOR(self, file: str, mode: str = "w") -> object: ...
    def on_file_received(self, file: str) -> None: ...
    def on_incomplete_file_received(self, file: str) -> None: ...
    def on_disconnect(self) -> None: ...


Harness = tuple[
    FtpReceiveService,
    Callable[[], TransferHandler],
    Path,
    asyncio.AbstractEventLoop,
    asyncio.Queue[ReceivedImage],
]


@pytest.fixture
def handlers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    import pyftpdlib.handlers
    import pyftpdlib.servers

    captured: list[type[TransferHandler]] = []
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    loop = asyncio.new_event_loop()
    queue: asyncio.Queue[ReceivedImage] = asyncio.Queue()
    service = FtpReceiveService(FtpConfig(incoming_dir=incoming, password="secure"), queue, loop)

    class Handler:
        def __init__(self) -> None:
            self.remote_ip = "192.168.8.10"
            self.replies: list[str] = []
            self.calls: list[tuple[str, str]] = []
            self.outcome = "success"

        def respond(self, reply: str) -> None:
            self.replies.append(reply)

        def ftp_STOR(self, file: str, mode: str = "w") -> str | None:
            self.calls.append((file, mode))
            if self.outcome == "failure":
                return None
            if self.outcome == "exception":
                raise OSError("cannot open")
            with Path(file).open(mode + "b") as stream:
                stream.write(b"new-upload")
            return file

    class Server:
        def __init__(self, _address: object, handler: type[TransferHandler]) -> None:
            captured.append(handler)

        def serve_forever(self) -> None:
            service._stopping = True

    monkeypatch.setattr(pyftpdlib.handlers, "FTPHandler", Handler)
    monkeypatch.setattr(pyftpdlib.servers, "FTPServer", Server)
    service._run_server()
    service._stopping = False

    def make() -> TransferHandler:
        handler = captured[0]()
        handler.on_connect()
        return handler

    yield service, make, incoming, loop, queue
    loop.close()


def test_owned_stor_rejected_before_truncation_and_release_allows_append(handlers: Harness) -> None:
    service, make, incoming, _, _ = handlers
    path = incoming / "held.hif"
    path.write_bytes(b"original")
    service._pin_received_image(path)
    handler = make()
    assert handler.ftp_STOR(str(path)) is None
    assert handler.replies[-1].startswith("450")
    assert not handler.calls
    assert path.read_bytes() == b"original"
    service.release_received_image(path)
    assert handler.ftp_STOR(str(path), "a") == str(path)
    assert handler.calls == [(str(path), "a")]
    assert path.read_bytes() == b"originalnew-upload"
    handler.on_incomplete_file_received(str(path))
    assert not service._upload_owners


@pytest.mark.parametrize("root_upload", [False, True])
def test_simultaneous_upload_cannot_open_same_source_and_completion_pins_job(
    handlers: Harness, root_upload: bool
) -> None:
    service, make, incoming, loop, queue = handlers
    path = (incoming.parent if root_upload else incoming) / "same.hif"
    first, second = make(), make()
    assert first.ftp_STOR(str(path)) == str(path)
    assert second.ftp_STOR(str(path)) is None
    assert not second.calls
    assert path.read_bytes() == b"new-upload"
    first.on_file_received(str(path))
    loop.run_until_complete(asyncio.sleep(0))
    received = queue.get_nowait()
    assert received.path.read_bytes() == b"new-upload"
    assert service._pending_paths == {received.path.resolve(): 1}
    assert not service._upload_owners
    if not root_upload:
        assert second.ftp_STOR(str(path)) is None
        assert not second.calls
    service.release_received_image(received.path)
    assert second.ftp_STOR(str(path)) == str(path)
    second.on_disconnect()
    assert not service._upload_owners


@pytest.mark.parametrize("cleanup", ["incomplete", "disconnect", "failure", "exception"])
def test_upload_reservation_released_on_every_aborted_setup(
    handlers: Harness, cleanup: str
) -> None:
    service, make, incoming, _, _ = handlers
    path = incoming / "retry.hif"
    handler = make()
    if cleanup in {"failure", "exception"}:
        handler.outcome = cleanup
    if cleanup == "exception":
        with pytest.raises(OSError):
            handler.ftp_STOR(str(path))
    else:
        handler.ftp_STOR(str(path))
        if cleanup == "incomplete":
            handler.on_incomplete_file_received(str(path))
        elif cleanup == "disconnect":
            handler.on_disconnect()
    assert not service._upload_owners
    retry = make()
    assert retry.ftp_STOR(str(path)) == str(path)
    retry.on_disconnect()


def test_legacy_shared_source_copy_failure_rejects_before_open_and_cleans_reservation(
    handlers: Harness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import os

    from instantlink_bridge.camera import ftp

    service, make, incoming, _, _ = handlers
    path = incoming / "legacy.hif"
    path.write_bytes(b"pending-original")
    pending = incoming.parent / "spooled.hif"
    os.link(path, pending)

    def fail_copy(source: Path, destination: Path) -> None:
        destination.write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(ftp.shutil, "copy2", fail_copy)
    handler = make()
    assert handler.ftp_STOR(str(path)) is None
    assert handler.replies[-1].startswith("450")
    assert not handler.calls
    assert not service._upload_owners
    assert path.read_bytes() == pending.read_bytes() == b"pending-original"
    assert set(incoming.iterdir()) == {path}
    assert "ftp.shared_source_detach_failed" in caplog.text


@pytest.mark.parametrize("mode", ["w", "a"])
def test_legacy_source_detach_preserves_original_and_append_bytes(
    handlers: Harness, mode: str
) -> None:
    import os

    service, make, incoming, _, _ = handlers
    path = incoming / "legacy.hif"
    path.write_bytes(b"pending-original")
    pending = incoming.parent / "spooled.hif"
    os.link(path, pending)
    handler = make()
    assert handler.ftp_STOR(str(path), mode) == str(path)
    assert pending.read_bytes() == b"pending-original"
    expected = b"new-upload" if mode == "w" else b"pending-originalnew-upload"
    assert path.read_bytes() == expected
    assert path.stat().st_ino != pending.stat().st_ino
    assert set(incoming.iterdir()) == {path}
    handler.on_disconnect()
    assert not service._upload_owners
