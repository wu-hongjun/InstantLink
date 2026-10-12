from __future__ import annotations

import asyncio
import ftplib
from collections.abc import AsyncIterator
from contextlib import closing
from pathlib import Path
from threading import Event

import pytest
import pytest_asyncio
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.ioloop import IOLoop
from pyftpdlib.servers import FTPServer

from instantlink_bridge.camera.ftp import FtpReceiveService, ReceivedImage
from instantlink_bridge.config import FtpConfig, FtpSourceDecision, FtpSourceKind

Receiver = tuple[FtpReceiveService, asyncio.Queue[ReceivedImage], int]


@pytest_asyncio.fixture
async def receiver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Receiver]:
    import pyftpdlib.servers

    servers: list[FTPServer] = []

    class LocalServer(FTPServer):
        def __init__(self, address: tuple[str, int], handler: type[FTPHandler]) -> None:
            self._close_requested = Event()
            # Isolate sockets and scheduled callbacks from other FTP tests.
            super().__init__(address, handler, ioloop=IOLoop())
            servers.append(self)

        def serve_forever(self) -> None:
            try:
                while not self._close_requested.is_set() and self.ioloop.socket_map:
                    self.ioloop.loop(timeout=0.02, blocking=False)
            finally:
                # kqueue/epoll descriptors must not close in another thread
                # while the owning loop is inside poll().
                FTPServer.close_all(self)

        def close_all(self) -> None:
            self._close_requested.set()

    monkeypatch.setattr(pyftpdlib.servers, "FTPServer", LocalServer)
    queue: asyncio.Queue[ReceivedImage] = asyncio.Queue()
    service = FtpReceiveService(
        FtpConfig(
            bind_host="127.0.0.1",
            port=0,
            incoming_dir=tmp_path / "incoming",
            password="test-upload-password",
        ),
        queue,
        asyncio.get_running_loop(),
    )
    # Production rejects loopback clients. Only the network-source policy is
    # substituted; real STOR, file handles and pyftpdlib callbacks remain in use.
    monkeypatch.setattr(service, "_accept_connection_source", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        service,
        "_source_decision",
        lambda _ip: FtpSourceDecision(True, FtpSourceKind.HOTSPOT, "allowed"),
    )
    await asyncio.wait_for(asyncio.to_thread(service.start), 6)
    try:
        yield service, queue, servers[0].socket.getsockname()[1]
    finally:
        await asyncio.wait_for(asyncio.to_thread(service.stop), 6)
        while not queue.empty():
            service.release_received_image(queue.get_nowait().path)
            queue.task_done()


def connect(service: FtpReceiveService, port: int) -> ftplib.FTP:
    client = ftplib.FTP(timeout=2)
    client.connect("127.0.0.1", port)
    client.login(service.config.username, service.config.password)
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize("root_upload", [False, True])
async def test_real_overlapping_stor_preserves_queued_source(
    receiver: Receiver, root_upload: bool
) -> None:
    service, queue, port = receiver
    destination = "/same.HIF" if root_upload else "/incoming/same.HIF"

    def upload() -> None:
        with closing(connect(service, port)) as first, closing(connect(service, port)) as second:
            with closing(first.transfercmd(f"STOR {destination}")) as stream:
                stream.sendall(b"AAAA")
                # The first transfer has an open file but no received-photo pin.
                # The second must be rejected before it can truncate that inode.
                with pytest.raises(ftplib.error_temp, match="450"):
                    second.transfercmd(f"STOR {destination}")
            first.voidresp()
            # 226 precedes the receive callback and its lease-release finally.
            # A subsequent command on this same control connection cannot
            # respond until that callback has finished in the FTP thread.
            first.voidcmd("NOOP")
            if root_upload:
                # A completed root upload moves into incoming, so the now-free
                # root pathname can accept a separate photo without touching A.
                with closing(second.transfercmd(f"STOR {destination}")) as stream:
                    stream.sendall(b"BBBBCCCC")
                second.voidresp()
                second.voidcmd("NOOP")
            else:
                with pytest.raises(ftplib.error_temp, match="450"):
                    second.transfercmd(f"STOR {destination}")

    await asyncio.wait_for(asyncio.to_thread(upload), 6)
    first = await asyncio.wait_for(queue.get(), 1)
    assert first.path.read_bytes() == b"AAAA"
    if root_upload:
        second = await asyncio.wait_for(queue.get(), 1)
        assert first.path != second.path
        assert second.path.read_bytes() == b"BBBBCCCC"
        service.release_received_image(second.path)
        queue.task_done()
    service.release_received_image(first.path)
    queue.task_done()
    assert not service._upload_owners
    assert not service._pending_paths


@pytest.mark.asyncio
async def test_real_disconnect_releases_open_upload_for_retry(receiver: Receiver) -> None:
    service, queue, port = receiver

    def abort_then_retry() -> None:
        first = connect(service, port)
        stream = first.transfercmd("STOR /incoming/retry.HIF")
        stream.sendall(b"partial")
        # Closing the control connection interrupts its still-open data stream.
        # A same-connection NOOP on the other client orders its next command
        # after pyftpdlib has processed the disconnect and closed the first FD.
        first.close()
        assert stream.recv(1) == b""
        stream.close()
        with closing(connect(service, port)) as retry:
            retry.voidcmd("NOOP")
            with closing(retry.transfercmd("STOR /incoming/retry.HIF")) as stream:
                stream.sendall(b"complete-retry")
            retry.voidresp()
            retry.voidcmd("NOOP")

    await asyncio.wait_for(asyncio.to_thread(abort_then_retry), 6)
    received = await asyncio.wait_for(queue.get(), 1)
    assert received.path.read_bytes() == b"complete-retry"
    assert queue.empty(), "an interrupted upload must not become a completed job"
    assert not service._upload_owners
    service.release_received_image(received.path)
    queue.task_done()
