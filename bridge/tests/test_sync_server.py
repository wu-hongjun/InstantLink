"""Tests for the iPhone sync HTTP service."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from instantlink_bridge.sync.outbox import SyncOutbox
from instantlink_bridge.sync.server import SyncService, load_or_create_sync_token


def _write_source(directory: Path, name: str, payload: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / name
    source.write_bytes(payload)
    return source


def _make_service(
    tmp_path: Path,
    *,
    client_activity_callback: object = None,
) -> tuple[SyncOutbox, SyncService]:
    outbox = SyncOutbox(tmp_path / "outbox", budget_mb=64)
    callback = client_activity_callback if callable(client_activity_callback) else None
    service = SyncService(
        outbox,
        port=8721,
        token_path=tmp_path / "sync.token",
        device_id="IB-TEST",
        client_activity_callback=callback,
        enable_zeroconf=False,
    )
    return outbox, service


def _auth(service: SyncService) -> dict[str, str]:
    return {"Authorization": f"Bearer {service.token}"}


async def _start_client(service: SyncService) -> TestClient:
    client = TestClient(TestServer(service.build_app()))
    await client.start_server()
    return client


# --- token file --------------------------------------------------------------


def test_load_or_create_sync_token_creates_and_persists(tmp_path: Path) -> None:
    token_path = tmp_path / "state" / "sync.token"
    token = load_or_create_sync_token(token_path)

    assert len(token) == 32
    int(token, 16)  # valid hex
    assert token_path.read_text(encoding="utf-8").strip() == token
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o640
    assert load_or_create_sync_token(token_path) == token


def test_load_or_create_sync_token_replaces_invalid_content(tmp_path: Path) -> None:
    token_path = tmp_path / "sync.token"
    token_path.write_text("not-a-valid-token\n", encoding="utf-8")

    token = load_or_create_sync_token(token_path)
    assert len(token) == 32
    int(token, 16)
    assert token_path.read_text(encoding="utf-8").strip() == token


def test_load_or_create_sync_token_accepts_padded_existing(tmp_path: Path) -> None:
    token_path = tmp_path / "sync.token"
    token_path.write_text("  0123456789abcdef0123456789abcdef \n", encoding="utf-8")

    assert load_or_create_sync_token(token_path) == "0123456789abcdef0123456789abcdef"


# --- auth ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_requests_without_token_are_rejected(tmp_path: Path) -> None:
    _, service = _make_service(tmp_path)
    client = await _start_client(service)
    try:
        for path in ("/v1/status", "/v1/queue", "/v1/photos/x"):
            response = await client.get(path)
            assert response.status == 401
            assert (await response.json()) == {"error": "unauthorized"}
        response = await client.post("/v1/photos/x/ack")
        assert response.status == 401
        assert service.last_client_seen_monotonic is None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_requests_with_wrong_token_are_rejected(tmp_path: Path) -> None:
    _, service = _make_service(tmp_path)
    client = await _start_client(service)
    try:
        wrong = {"Authorization": "Bearer " + "0" * 32}
        response = await client.get("/v1/status", headers=wrong)
        assert response.status == 401
        response = await client.get("/v1/status", headers={"Authorization": service.token})
        assert response.status == 401
        assert service.last_client_seen_monotonic is None
    finally:
        await client.close()


# --- endpoints ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_reports_identity_and_depth(tmp_path: Path) -> None:
    outbox, service = _make_service(tmp_path)
    outbox.add(_write_source(tmp_path / "u", "one.jpg", b"one"))
    client = await _start_client(service)
    try:
        response = await client.get("/v1/status", headers=_auth(service))
        assert response.status == 200
        assert (await response.json()) == {
            "device": "IB-TEST",
            "proto": 1,
            "outbox_depth": 1,
        }
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_queue_lists_items_oldest_first(tmp_path: Path) -> None:
    outbox, service = _make_service(tmp_path)
    first = outbox.add(_write_source(tmp_path / "u", "first.jpg", b"first"), remote_ip="10.0.0.9")
    second = outbox.add(_write_source(tmp_path / "u", "second.jpg", b"second-body"))
    client = await _start_client(service)
    try:
        response = await client.get("/v1/queue", headers=_auth(service))
        assert response.status == 200
        payload = await response.json()
        assert [entry["item_id"] for entry in payload["items"]] == [
            first.item_id,
            second.item_id,
        ]
        head = payload["items"][0]
        assert head["file_name"] == "first.jpg"
        assert head["size_bytes"] == len(b"first")
        assert head["sha256"] == first.sha256
        assert head["received_at"] == pytest.approx(first.received_at)
        assert head["source_remote_ip"] == "10.0.0.9"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_photo_download_returns_file_bytes(tmp_path: Path) -> None:
    outbox, service = _make_service(tmp_path)
    payload = b"jpeg-body-" * 64
    item = outbox.add(_write_source(tmp_path / "u", "photo.jpg", payload))
    client = await _start_client(service)
    try:
        response = await client.get(f"/v1/photos/{item.item_id}", headers=_auth(service))
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/jpeg"
        assert (await response.read()) == payload
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_photo_download_supports_range_resume(tmp_path: Path) -> None:
    outbox, service = _make_service(tmp_path)
    payload = b"0123456789abcdef"
    item = outbox.add(_write_source(tmp_path / "u", "photo.jpg", payload))
    client = await _start_client(service)
    try:
        response = await client.get(
            f"/v1/photos/{item.item_id}",
            headers={**_auth(service), "Range": "bytes=4-7"},
        )
        assert response.status == 206
        assert (await response.read()) == b"4567"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_photo_download_unknown_id_is_404(tmp_path: Path) -> None:
    _, service = _make_service(tmp_path)
    client = await _start_client(service)
    try:
        response = await client.get("/v1/photos/deadbeefdeadbeef", headers=_auth(service))
        assert response.status == 404
        assert (await response.json())["error"] == "unknown_item"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_ack_removes_item_and_spool_file(tmp_path: Path) -> None:
    outbox, service = _make_service(tmp_path)
    item = outbox.add(_write_source(tmp_path / "u", "done.jpg", b"done"))
    spool_path = outbox.path_for(item.item_id)
    assert spool_path is not None
    client = await _start_client(service)
    try:
        response = await client.post(f"/v1/photos/{item.item_id}/ack", headers=_auth(service))
        assert response.status == 200
        assert (await response.json()) == {"ok": True}
        assert outbox.depth() == 0
        assert not spool_path.exists()

        response = await client.post(f"/v1/photos/{item.item_id}/ack", headers=_auth(service))
        assert response.status == 404
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_authenticated_requests_fire_activity_callback(tmp_path: Path) -> None:
    calls: list[int] = []
    _, service = _make_service(tmp_path, client_activity_callback=lambda: calls.append(1))
    client = await _start_client(service)
    try:
        assert service.last_client_seen_monotonic is None
        await client.get("/v1/status", headers=_auth(service))
        assert len(calls) == 1
        first_seen = service.last_client_seen_monotonic
        assert first_seen is not None
        await client.get("/v1/queue", headers=_auth(service))
        assert len(calls) == 2
        seen = service.last_client_seen_monotonic
        assert seen is not None
        assert seen >= first_seen
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_activity_callback_exceptions_do_not_break_requests(tmp_path: Path) -> None:
    def _boom() -> None:
        raise RuntimeError("callback exploded")

    _, service = _make_service(tmp_path, client_activity_callback=_boom)
    client = await _start_client(service)
    try:
        response = await client.get("/v1/status", headers=_auth(service))
        assert response.status == 200
        assert service.last_client_seen_monotonic is not None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_start_and_stop_without_zeroconf(tmp_path: Path) -> None:
    outbox = SyncOutbox(tmp_path / "outbox", budget_mb=64)
    service = SyncService(
        outbox,
        port=0,  # ephemeral port keeps the test hermetic
        token_path=tmp_path / "sync.token",
        device_id="IB-TEST",
        enable_zeroconf=False,
    )
    await service.start()
    await service.start()  # idempotent
    await service.stop()
    await service.stop()  # idempotent
