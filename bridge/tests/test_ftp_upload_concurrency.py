from __future__ import annotations

import asyncio
import ftplib
import socket
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


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["STOR", "APPE", "REST"])
async def test_pending_sync_original_survives_same_name_ftp_mutation(
    receiver: Receiver, tmp_path: Path, command: str
) -> None:
    import hashlib

    from instantlink_bridge.sync.outbox import SyncOutbox

    service, queue, port = receiver
    first_bytes = b"original-camera-photo"
    replacement = b"replacement"

    def upload(payload: bytes, *, mutation: bool = False) -> None:
        with closing(connect(service, port)) as client:
            client.voidcmd("TYPE I")
            if mutation and command == "REST":
                client.sendcmd("REST 4")
            verb = "APPE" if mutation and command == "APPE" else "STOR"
            with closing(client.transfercmd(f"{verb} /incoming/reused.HIF")) as stream:
                stream.sendall(payload)
            client.voidresp()
            client.voidcmd("NOOP")

    await asyncio.wait_for(asyncio.to_thread(upload, first_bytes), 3)
    first = await asyncio.wait_for(queue.get(), 1)
    outbox = SyncOutbox(tmp_path / "outbox", budget_mb=64)
    item = await asyncio.to_thread(outbox.add, first.path)
    spool = outbox.path_for(item.item_id)
    assert spool is not None
    assert (spool.stat().st_dev, spool.stat().st_ino) != (
        first.path.stat().st_dev,
        first.path.stat().st_ino,
    )
    service.release_received_image(first.path)
    queue.task_done()

    if command == "APPE":
        # The camera account does not have append permission. Keep that
        # restriction and prove rejected appends preserve the pending photo.
        with pytest.raises(ftplib.error_perm, match="550"):
            await asyncio.wait_for(asyncio.to_thread(upload, replacement, mutation=True), 3)
        assert queue.empty()
    else:
        await asyncio.wait_for(asyncio.to_thread(upload, replacement, mutation=True), 3)
        second = await asyncio.wait_for(queue.get(), 1)
        assert second.path == first.path
        assert second.path.read_bytes() != first_bytes
        service.release_received_image(second.path)
        queue.task_done()
    assert spool.read_bytes() == first_bytes
    assert spool.stat().st_size == item.size_bytes == len(first_bytes)
    assert hashlib.sha256(spool.read_bytes()).hexdigest() == item.sha256
    assert SyncOutbox(tmp_path / "outbox", budget_mb=64).get(item.item_id) == item


@pytest.mark.asyncio
async def test_real_overflow_cleanup_finishes_before_same_name_retry_can_open(
    receiver: Receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, queue, port = receiver
    queue._maxsize = 1
    queue.put_nowait(ReceivedImage(service.config.incoming_dir / "held.HIF", "camera"))
    path = service.config.incoming_dir / "race.HIF"
    deleting, allow_delete, deletion_done = Event(), Event(), Event()
    retry_reservation = Event()
    original_unlink = Path.unlink
    original_reserve = service._reserve_upload

    def held_unlink(item: Path, *args: object, **kwargs: object) -> None:
        if item == path and not deletion_done.is_set():
            deleting.set()
            assert allow_delete.wait(3), "retry did not attempt reservation"
            original_unlink(item, *args, **kwargs)
            deletion_done.set()
        else:
            original_unlink(item, *args, **kwargs)

    def reserve(item: Path, owner: object) -> bool:
        retry = item == path and deleting.is_set()
        if retry:
            retry_reservation.set()
            allow_delete.set()
        accepted = original_reserve(item, owner)
        if retry and accepted:
            assert deletion_done.is_set(), "retry opened before prior overflow deletion"
        return accepted

    monkeypatch.setattr(Path, "unlink", held_unlink)
    monkeypatch.setattr(service, "_reserve_upload", reserve)
    loop = asyncio.get_running_loop()

    def drop_filler() -> None:
        queue.get_nowait()
        queue.task_done()

    def uploads() -> None:
        try:
            with (
                closing(connect(service, port)) as first,
                closing(connect(service, port)) as second,
            ):
                second.voidcmd("TYPE I")
                retry_address = second.makepasv()
                retry_stream = socket.create_connection(retry_address, timeout=2)
                with closing(first.transfercmd("STOR /incoming/race.HIF")) as stream:
                    stream.sendall(b"overflowed-photo")
                first.voidresp()
                assert deleting.wait(3)
                assert path.resolve() in service._pending_paths, (
                    "cleanup released its pin too early"
                )
                loop.call_soon_threadsafe(drop_filler)
                second.putcmd("STOR /incoming/race.HIF")
                allow_delete.set()
                assert second.getresp().startswith("1")
                with closing(retry_stream) as stream:
                    stream.sendall(b"retained-retry")
                second.voidresp()
                second.voidcmd("NOOP")
                assert retry_reservation.is_set()
        finally:
            allow_delete.set()

    await asyncio.wait_for(asyncio.to_thread(uploads), 8)
    received = await asyncio.wait_for(queue.get(), 1)
    assert received.path == path
    assert path.read_bytes() == b"retained-retry"
    service.release_received_image(path)
    queue.task_done()
    assert not service._pending_paths
    assert not service._upload_owners


@pytest.mark.asyncio
@pytest.mark.parametrize("restart_offset", [None, 4])
async def test_real_ftp_preserves_legacy_outbox_before_deferred_sync_reload(
    receiver: Receiver, tmp_path: Path, restart_offset: int | None
) -> None:
    import hashlib
    import os

    from instantlink_bridge.sync.outbox import SyncOutbox

    service, queue, port = receiver
    source = service.config.incoming_dir / "legacy.HIF"
    original = b"legacy-original-photo"
    source.write_bytes(original)
    outbox = SyncOutbox(tmp_path / "outbox", budget_mb=64)
    item = outbox.add(source)
    spool = outbox.path_for(item.item_id)
    assert spool is not None
    spool.unlink()
    os.link(source, spool)
    assert source.stat().st_ino == spool.stat().st_ino

    def upload() -> None:
        with closing(connect(service, port)) as client:
            client.voidcmd("TYPE I")
            if restart_offset is not None:
                client.sendcmd(f"REST {restart_offset}")
            with closing(client.transfercmd("STOR /incoming/legacy.HIF")) as stream:
                stream.sendall(b"new")
            client.voidresp()
            client.voidcmd("NOOP")

    # Sync has not reloaded or migrated the persisted index yet.
    await asyncio.wait_for(asyncio.to_thread(upload), 3)
    received = await asyncio.wait_for(queue.get(), 1)
    expected_incoming = b"new" if restart_offset is None else b"leganeworiginal-photo"
    assert received.path.read_bytes() == expected_incoming
    assert spool.read_bytes() == original
    assert spool.stat().st_size == item.size_bytes
    assert hashlib.sha256(spool.read_bytes()).hexdigest() == item.sha256
    assert SyncOutbox(tmp_path / "outbox", budget_mb=64).get(item.item_id) == item
    assert set(source.parent.iterdir()) == {source}
    service.release_received_image(received.path)
    queue.task_done()
