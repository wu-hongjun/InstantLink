"""Tests for the Phase E diagnostics surface.

Covers:

* SSE log redaction at the formatter layer.
* ``/v1/logs/stream`` GET happy path with the test client driving a
  scripted :class:`LogStreamSource`.
* Support-bundle creation: redacted zip layout + ``/v1/support-bundle/create``
  HTTP handler.
"""

from __future__ import annotations

import hashlib
import io
import json
import random
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

import pytest
from aiohttp.test_utils import TestClient, TestServer

from instantlink_bridge.manager.api import create_app
from instantlink_bridge.manager.auth import (
    CLIENT_ID_HEADER,
    NONCE_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    AuthorizedClient,
    ClientStore,
    SignedRequestVerifier,
    canonical_request_payload,
    encode_base64url,
    public_key_text,
)
from instantlink_bridge.manager.diagnostics import (
    BridgeLogEvent,
    LogStreamSource,
    SupportBundleSource,
    _file_sha256,
    create_support_bundle,
    format_sse_event,
    redact_log_line,
)

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )


ed25519 = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")


class SigningPrivateKey(Protocol):
    def sign(self, data: bytes) -> bytes: ...

    def public_key(self) -> Ed25519PublicKey: ...


def _private_key() -> Ed25519PrivateKey:
    key: Ed25519PrivateKey = ed25519.Ed25519PrivateKey.generate()
    return key


def _verifier(tmp_path: Path, private_key: SigningPrivateKey) -> SignedRequestVerifier:
    store = ClientStore(tmp_path / "clients")
    store.save_client(
        AuthorizedClient(
            client_id="macbook",
            client_name="Test Mac",
            public_key=public_key_text(private_key.public_key()),
            created_at="2026-05-26T15:30:00Z",
        )
    )
    return SignedRequestVerifier(store, now_seconds=lambda: 1000)


def _signed_headers(
    private_key: SigningPrivateKey,
    *,
    method: str,
    path: str,
    body: bytes = b"",
    timestamp: int = 1000,
    nonce: str = "nonce-0001",
    client_id: str = "macbook",
) -> dict[str, str]:
    signature = private_key.sign(
        canonical_request_payload(
            method=method,
            path=path,
            body_sha256=hashlib.sha256(body).hexdigest(),
            timestamp=timestamp,
            nonce=nonce,
        )
    )
    return {
        CLIENT_ID_HEADER: client_id,
        TIMESTAMP_HEADER: str(timestamp),
        NONCE_HEADER: nonce,
        SIGNATURE_HEADER: encode_base64url(signature),
    }


def _make_log_events() -> list[BridgeLogEvent]:
    return [
        BridgeLogEvent(
            event_id="evt-1",
            timestamp="2026-05-30T10:00:00Z",
            level="info",
            message="bridge.boot ready",
        ),
        BridgeLogEvent(
            event_id="evt-2",
            timestamp="2026-05-30T10:00:01Z",
            level="warning",
            message="bridge.printer reconnect_pending",
        ),
        BridgeLogEvent(
            event_id="evt-3",
            timestamp="2026-05-30T10:00:02Z",
            level="error",
            message="bridge.ftp upload_failed reason=timeout",
        ),
    ]


# --- Redaction -------------------------------------------------------------


def test_redact_log_line_masks_password_assignment() -> None:
    assert redact_log_line('password = "hunter2"') == 'password = "***redacted***"'
    assert redact_log_line("psk: supersecret") == "psk: ***redacted***"
    assert "Bearer ***redacted***" in redact_log_line(
        "Authorization header Bearer eyJhbGciOiJIUzI1NiJ9"
    )


def test_redact_log_line_leaves_normal_text_intact() -> None:
    line = "bridge.printer connected device_id=IB-1234ABCD"
    assert redact_log_line(line) == line


# --- SSE formatter ---------------------------------------------------------


def test_format_sse_event_encodes_log_event_with_id_and_json_payload() -> None:
    event = BridgeLogEvent(
        event_id="evt-9",
        timestamp="2026-05-30T10:00:00Z",
        level="info",
        message="ready",
    )
    record = format_sse_event(event).decode()
    assert record.startswith("id: evt-9\n")
    assert "event: log\n" in record
    data_line = next(line for line in record.splitlines() if line.startswith("data: "))
    payload = json.loads(data_line.removeprefix("data: "))
    assert payload == {
        "id": "evt-9",
        "timestamp": "2026-05-30T10:00:00Z",
        "level": "info",
        "message": "ready",
    }


# --- LogStreamSource filtering --------------------------------------------


@pytest.mark.asyncio
async def test_log_stream_source_filters_by_level() -> None:
    source = LogStreamSource(_make_log_events())
    seen = [event async for event in source.iter_events(level_filter="error")]
    assert [event.event_id for event in seen] == ["evt-3"]


@pytest.mark.asyncio
async def test_log_stream_source_emits_all_when_filter_is_none_or_all() -> None:
    source = LogStreamSource(_make_log_events())
    all_events_none = [event async for event in source.iter_events(level_filter=None)]
    all_events_all = [event async for event in source.iter_events(level_filter="all")]
    assert [event.event_id for event in all_events_none] == ["evt-1", "evt-2", "evt-3"]
    assert [event.event_id for event in all_events_all] == ["evt-1", "evt-2", "evt-3"]


# --- HTTP /v1/logs/stream --------------------------------------------------


@pytest.mark.asyncio
async def test_logs_stream_route_requires_signed_request(tmp_path: Path) -> None:
    private_key = _private_key()
    app = create_app(
        config_path=tmp_path / "missing.toml",
        request_id_factory=lambda: "req-logs",
        auth_verifier=_verifier(tmp_path, private_key),
        log_stream_source=LogStreamSource(_make_log_events()),
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        response = await client.get("/v1/logs/stream")
        data = cast(dict[str, Any], await response.json())
        assert response.status == 401
        assert data["error_code"] == "auth_required"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_logs_stream_route_emits_sse_records_for_scripted_source(
    tmp_path: Path,
) -> None:
    private_key = _private_key()
    app = create_app(
        config_path=tmp_path / "missing.toml",
        request_id_factory=lambda: "req-logs",
        auth_verifier=_verifier(tmp_path, private_key),
        log_stream_source=LogStreamSource(_make_log_events()),
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        path = "/v1/logs/stream"
        response = await client.get(
            path,
            headers=_signed_headers(private_key, method="GET", path=path),
        )
        body = await response.read()
        text = body.decode()
        assert response.status == 200
        assert response.headers.get("Content-Type", "").startswith("text/event-stream")
        # Each event surfaces as its own SSE record.
        assert text.count("event: log") == 3
        assert "id: evt-1" in text
        assert "id: evt-2" in text
        assert "id: evt-3" in text
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_logs_stream_route_filter_by_level_drops_other_events(
    tmp_path: Path,
) -> None:
    private_key = _private_key()
    app = create_app(
        config_path=tmp_path / "missing.toml",
        request_id_factory=lambda: "req-logs",
        auth_verifier=_verifier(tmp_path, private_key),
        log_stream_source=LogStreamSource(_make_log_events()),
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        path = "/v1/logs/stream?level=error"
        response = await client.get(
            path,
            headers=_signed_headers(private_key, method="GET", path=path),
        )
        text = (await response.read()).decode()
        assert response.status == 200
        assert "id: evt-3" in text
        assert "id: evt-1" not in text
        assert "id: evt-2" not in text
    finally:
        await client.close()


# --- Support bundle --------------------------------------------------------


@pytest.mark.parametrize("size", [0, 1, 262143, 262144, 262145, 1048576])
def test_file_sha256_matches_whole_file_digest(tmp_path: Path, size: int) -> None:
    # Exercise empty input, partial reads, and the default file_digest buffer boundary.
    payload = random.Random(42).randbytes(size)
    path = tmp_path / "archive.zip"
    path.write_bytes(payload)

    assert _file_sha256(path) == hashlib.sha256(payload).hexdigest()


def test_file_sha256_propagates_read_errors_and_closes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "archive.zip"
    path.write_bytes(b"archive bytes")

    class FailingReader(io.BufferedReader):
        def readinto(self, buffer: object) -> int:
            raise OSError("archive read failed")

    reader = FailingReader(io.FileIO(path, "rb"))
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: reader)

    with pytest.raises(OSError, match="archive read failed"):
        _file_sha256(path)
    assert reader.closed


def test_file_sha256_reads_bounded_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = random.Random(42).randbytes(1048576)
    path = tmp_path / "archive.zip"
    path.write_bytes(payload)
    read_sizes: list[int] = []

    class BoundedReader(io.BufferedReader):
        def read(self, size: int | None = -1) -> bytes:
            pytest.fail("hashing must use bounded reads into a reusable buffer")

        def readinto(self, buffer: object) -> int:
            assert isinstance(buffer, bytearray)
            assert 0 < len(buffer) <= 262144
            read_sizes.append(len(buffer))
            return super().readinto(buffer)

    reader = BoundedReader(io.FileIO(path, "rb"))
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: reader)

    assert _file_sha256(path) == hashlib.sha256(payload).hexdigest()
    assert len(read_sizes) > 1
    assert reader.closed


def test_create_support_bundle_hashes_completed_zip_without_read_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = random.Random(42).randbytes(1048576).hex()

    def reject_whole_file_read(path: Path) -> bytes:
        pytest.fail(f"unexpected whole-file read: {path}")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", reject_whole_file_read)
        result = create_support_bundle(
            bundles_dir=tmp_path,
            sources=(),
            extra_payloads={"large-log.txt": payload},
            bundle_id="bounded-hash",
        )

    assert result.size_bytes > 1048576
    assert result.sha256 == hashlib.sha256(result.archive_path.read_bytes()).hexdigest()
    with zipfile.ZipFile(result.archive_path) as archive:
        assert archive.testzip() is None
        assert archive.read("large-log.txt").decode() == payload


def _write(path: Path, contents: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return path


def test_create_support_bundle_writes_redacted_zip_with_manifest(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "root"
    bundles_dir = tmp_path / "support"

    config_path = _write(
        source_root / "etc" / "InstantLinkBridge" / "config.toml",
        'quality = 100\npassword = "hunter2"\n',
    )
    log_path = _write(
        source_root / "var" / "log" / "instantlink-bridge.log",
        "bridge.boot ready\npsk = topsecret\n",
    )

    result = create_support_bundle(
        bundles_dir=bundles_dir,
        sources=(
            SupportBundleSource(
                archive_path="etc/InstantLinkBridge/config.toml",
                on_disk_path=config_path,
            ),
            SupportBundleSource(
                archive_path="var/log/instantlink-bridge.log",
                on_disk_path=log_path,
            ),
            SupportBundleSource(
                archive_path="absent.txt",
                on_disk_path=source_root / "absent.txt",
            ),
        ),
        bundle_id="support-test",
        created_at="2026-05-30T10:00:00Z",
        now_seconds=0,
    )

    archive = bundles_dir / "support-test.zip"
    assert result.archive_path == archive
    assert archive.exists()
    assert result.sha256 == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert result.size_bytes == archive.stat().st_size
    assert "manifest.json" in result.contents
    assert "etc/InstantLinkBridge/config.toml" in result.contents
    assert "var/log/instantlink-bridge.log" in result.contents
    assert "absent.txt" not in result.contents

    with zipfile.ZipFile(archive, mode="r") as zf:
        manifest = json.loads(zf.read("manifest.json").decode())
        assert manifest["bundle_id"] == "support-test"
        assert manifest["bundle_kind"] == "instantlink_bridge_support"
        config_bytes = zf.read("etc/InstantLinkBridge/config.toml").decode()
        assert "hunter2" not in config_bytes
        assert "***redacted***" in config_bytes
        log_bytes = zf.read("var/log/instantlink-bridge.log").decode()
        assert "topsecret" not in log_bytes
        assert "***redacted***" in log_bytes


@pytest.mark.asyncio
async def test_support_bundle_create_route_returns_bundle_metadata(
    tmp_path: Path,
) -> None:
    private_key = _private_key()
    bundles_dir = tmp_path / "bundles"
    source_root = tmp_path / "root"
    config_path = _write(
        source_root / "etc" / "InstantLinkBridge" / "config.toml",
        'quality = 100\npassword = "hunter2"\n',
    )

    app = create_app(
        config_path=tmp_path / "missing.toml",
        request_id_factory=lambda: "req-bundle",
        auth_verifier=_verifier(tmp_path, private_key),
        support_bundle_dir=bundles_dir,
        support_bundle_sources=(
            SupportBundleSource(
                archive_path="etc/InstantLinkBridge/config.toml",
                on_disk_path=config_path,
            ),
        ),
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        path = "/v1/support-bundle/create"
        response = await client.post(
            path,
            headers=_signed_headers(private_key, method="POST", path=path),
        )
        data = cast(dict[str, Any], await response.json())
        assert response.status == 200
        assert data["ok"] is True
        bundle = data["support_bundle"]
        assert bundle["schema_version"] == 1
        assert bundle["bundle_id"].startswith("support-")
        assert (
            "etc/InstantLinkBridge/config.toml" in bundle["contents"]
            and "manifest.json" in bundle["contents"]
        )
    finally:
        await client.close()

    _assert_bundle_on_disk(
        archive_path=Path(bundle["archive_path"]),
        expected_parent=bundles_dir,
        expected_sha256=bundle["sha256"],
    )


def _assert_bundle_on_disk(
    *,
    archive_path: Path,
    expected_parent: Path,
    expected_sha256: str,
) -> None:
    """Synchronous assertion helper so async tests can stay ASYNC240-clean."""

    assert archive_path.exists()
    assert archive_path.parent == expected_parent
    assert expected_sha256 == hashlib.sha256(archive_path.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive_path, mode="r") as zf:
        payload = zf.read("etc/InstantLinkBridge/config.toml").decode()
        assert "hunter2" not in payload
        assert "***redacted***" in payload


def _expect_mapping(value: object) -> Mapping[str, Any]:
    assert isinstance(value, Mapping)
    return value
