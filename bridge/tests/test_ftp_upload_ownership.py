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
