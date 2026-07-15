"""Tests for the iPhone sync HTTP service."""

from __future__ import annotations

import io
import re
import stat
from collections.abc import Callable
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

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
    outbox_changed_callback: object = None,
    screen_provider: Callable[[], Image.Image | None] | None = None,
    input_injector: Callable[[str], bool] | None = None,
    remote_ui_enabled: bool = True,
) -> tuple[SyncOutbox, SyncService]:
    outbox = SyncOutbox(tmp_path / "outbox", budget_mb=64)
    callback = client_activity_callback if callable(client_activity_callback) else None
    depth_callback = outbox_changed_callback if callable(outbox_changed_callback) else None
    service = SyncService(
        outbox,
        port=8721,
        token_path=tmp_path / "sync.token",
        device_id="IB-TEST",
        client_activity_callback=callback,
        outbox_changed_callback=depth_callback,
        enable_zeroconf=False,
        screen_provider=screen_provider,
        input_injector=input_injector,
        remote_ui_enabled=remote_ui_enabled,
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
async def test_ack_fires_outbox_changed_callback_with_new_depth(tmp_path: Path) -> None:
    """Plan 051 P1.2: draining the queue must notify the UI per ack so the
    LCD outbox chip decrements instead of reading "N pending" forever."""

    depths: list[int] = []
    outbox, service = _make_service(tmp_path, outbox_changed_callback=depths.append)
    first = outbox.add(_write_source(tmp_path / "u", "a.jpg", b"a"))
    second = outbox.add(_write_source(tmp_path / "u", "b.jpg", b"b"))
    client = await _start_client(service)
    try:
        response = await client.post(f"/v1/photos/{first.item_id}/ack", headers=_auth(service))
        assert response.status == 200
        assert depths == [1]

        response = await client.post(f"/v1/photos/{second.item_id}/ack", headers=_auth(service))
        assert response.status == 200
        assert depths == [1, 0]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_failed_ack_does_not_fire_outbox_changed_callback(tmp_path: Path) -> None:
    depths: list[int] = []
    _, service = _make_service(tmp_path, outbox_changed_callback=depths.append)
    client = await _start_client(service)
    try:
        response = await client.post("/v1/photos/unknown/ack", headers=_auth(service))
        assert response.status == 404
        assert depths == []
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_outbox_changed_callback_exception_does_not_break_ack(tmp_path: Path) -> None:
    def _boom(depth: int) -> None:
        raise RuntimeError("callback exploded")

    outbox, service = _make_service(tmp_path, outbox_changed_callback=_boom)
    item = outbox.add(_write_source(tmp_path / "u", "c.jpg", b"c"))
    client = await _start_client(service)
    try:
        response = await client.post(f"/v1/photos/{item.item_id}/ack", headers=_auth(service))
        assert response.status == 200
        assert (await response.json()) == {"ok": True}
        assert outbox.depth() == 0
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


# --- zeroconf advertisement refresh ------------------------------------------


def _install_fake_zeroconf(
    monkeypatch: pytest.MonkeyPatch,
) -> list[_FakeAsyncZeroconf]:
    import instantlink_bridge.sync.server as sync_server

    instances: list[_FakeAsyncZeroconf] = []

    class _Bound(_FakeAsyncZeroconf):
        def __init__(self, ip_version: object = None) -> None:
            super().__init__(ip_version)
            instances.append(self)

    monkeypatch.setattr(sync_server, "AsyncZeroconf", _Bound)
    return instances


class _FakeAsyncZeroconf:
    def __init__(self, ip_version: object = None) -> None:
        self.registered: list[object] = []
        self.updated: list[object] = []
        self.closed = False

    async def async_register_service(self, info: object) -> None:
        self.registered.append(info)

    async def async_update_service(self, info: object) -> None:
        self.updated.append(info)

    async def async_unregister_service(self, info: object) -> None:
        pass

    async def async_close(self) -> None:
        self.closed = True


def _make_refresh_service(
    tmp_path: Path,
    addresses: list[str],
) -> SyncService:
    outbox = SyncOutbox(tmp_path / "outbox", budget_mb=64)
    return SyncService(
        outbox,
        port=8721,
        token_path=tmp_path / "sync.token",
        device_id="IB-TEST",
        enable_zeroconf=True,
        address_provider=lambda: list(addresses),
    )


@pytest.mark.asyncio
async def test_refresh_zeroconf_registers_when_addresses_appear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    instances = _install_fake_zeroconf(monkeypatch)
    addresses: list[str] = []
    service = _make_refresh_service(tmp_path, addresses)

    await service.refresh_zeroconf()
    assert instances == []  # nothing to advertise yet

    addresses.append("192.168.8.1")
    await service.refresh_zeroconf()
    assert len(instances) == 1
    assert len(instances[0].registered) == 1
    info = instances[0].registered[0]
    assert info.addresses == [socket.inet_aton("192.168.8.1")]
    await service.stop()


@pytest.mark.asyncio
async def test_refresh_zeroconf_updates_when_addresses_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    instances = _install_fake_zeroconf(monkeypatch)
    addresses = ["192.168.7.1"]
    service = _make_refresh_service(tmp_path, addresses)

    await service.refresh_zeroconf()
    assert len(instances) == 1
    assert len(instances[0].registered) == 1

    addresses.insert(0, "192.168.8.1")
    await service.refresh_zeroconf()
    assert len(instances) == 1  # same zeroconf instance, updated in place
    assert len(instances[0].updated) == 1
    info = instances[0].updated[0]
    assert info.addresses == [
        socket.inet_aton("192.168.8.1"),
        socket.inet_aton("192.168.7.1"),
    ]
    await service.stop()


@pytest.mark.asyncio
async def test_refresh_zeroconf_noop_when_addresses_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instances = _install_fake_zeroconf(monkeypatch)
    addresses = ["192.168.8.1"]
    service = _make_refresh_service(tmp_path, addresses)

    await service.refresh_zeroconf()
    await service.refresh_zeroconf()
    assert len(instances) == 1
    assert len(instances[0].registered) == 1
    assert instances[0].updated == []
    await service.stop()


# --- token rotation (plan 051 P3.11) -----------------------------------------


def test_rotate_sync_token_replaces_file_with_fresh_token(tmp_path: Path) -> None:
    from instantlink_bridge.sync.server import rotate_sync_token

    path = tmp_path / "sync.token"
    old = load_or_create_sync_token(path)

    new = rotate_sync_token(path)

    assert new != old
    assert re.fullmatch(r"[0-9a-f]{32}", new)
    assert path.read_text(encoding="utf-8").strip() == new
    assert (path.stat().st_mode & 0o777) == 0o640


def test_rotate_sync_token_works_when_file_missing(tmp_path: Path) -> None:
    from instantlink_bridge.sync.server import rotate_sync_token

    path = tmp_path / "sync.token"

    new = rotate_sync_token(path)

    assert re.fullmatch(r"[0-9a-f]{32}", new)
    assert path.read_text(encoding="utf-8").strip() == new


@pytest.mark.asyncio
async def test_start_reloads_rotated_token_from_disk(tmp_path: Path) -> None:
    """SyncService caches the token in __init__; a restart must re-read the
    file so app.py's rotation restart actually swaps the enforced token."""

    outbox = SyncOutbox(tmp_path / "outbox", budget_mb=64)
    token_path = tmp_path / "sync.token"
    token_path.write_text("aa" * 16 + "\n", encoding="utf-8")
    service = SyncService(
        outbox,
        port=0,  # ephemeral port keeps the test hermetic
        token_path=token_path,
        device_id="IB-TEST",
        enable_zeroconf=False,
    )
    assert service.token == "aa" * 16

    token_path.write_text("bb" * 16 + "\n", encoding="utf-8")
    await service.start()
    try:
        assert service.token == "bb" * 16
    finally:
        await service.stop()

    token_path.write_text("cc" * 16 + "\n", encoding="utf-8")
    await service.start()
    try:
        assert service.token == "cc" * 16
    finally:
        await service.stop()


# --- virtual LCD (plan 054): GET /v1/screen + POST /v1/input -------------------


def _lcd_frame(color: tuple[int, int, int] = (12, 34, 56)) -> Image.Image:
    return Image.new("RGB", (240, 240), color)


@pytest.mark.asyncio
async def test_screen_and_input_require_token(tmp_path: Path) -> None:
    _, service = _make_service(
        tmp_path,
        screen_provider=_lcd_frame,
        input_injector=lambda action: True,
    )
    client = await _start_client(service)
    try:
        response = await client.get("/v1/screen")
        assert response.status == 401
        response = await client.post("/v1/input", json={"action": "up"})
        assert response.status == 401
        assert service.last_client_seen_monotonic is None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_screen_returns_current_frame_as_png(tmp_path: Path) -> None:
    _, service = _make_service(tmp_path, screen_provider=lambda: _lcd_frame((200, 10, 10)))
    client = await _start_client(service)
    try:
        response = await client.get("/v1/screen", headers=_auth(service))
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/png"
        decoded = Image.open(io.BytesIO(await response.read()))
        assert decoded.format == "PNG"
        assert decoded.size == (240, 240)
        assert decoded.convert("RGB").getpixel((120, 120)) == (200, 10, 10)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_screen_without_provider_is_404(tmp_path: Path) -> None:
    _, service = _make_service(tmp_path)
    client = await _start_client(service)
    try:
        response = await client.get("/v1/screen", headers=_auth(service))
        assert response.status == 404
        assert (await response.json()) == {"error": "remote_ui_unavailable"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_screen_provider_returning_none_is_404(tmp_path: Path) -> None:
    _, service = _make_service(tmp_path, screen_provider=lambda: None)
    client = await _start_client(service)
    try:
        response = await client.get("/v1/screen", headers=_auth(service))
        assert response.status == 404
        assert (await response.json()) == {"error": "remote_ui_unavailable"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_remote_ui_disabled_by_config_is_404(tmp_path: Path) -> None:
    """[sync] remote_ui = false must 404 both endpoints even when wired."""

    injected: list[str] = []

    def _inject(action: str) -> bool:
        injected.append(action)
        return True

    _, service = _make_service(
        tmp_path,
        screen_provider=_lcd_frame,
        input_injector=_inject,
        remote_ui_enabled=False,
    )
    client = await _start_client(service)
    try:
        response = await client.get("/v1/screen", headers=_auth(service))
        assert response.status == 404
        assert (await response.json()) == {"error": "remote_ui_disabled"}
        response = await client.post("/v1/input", json={"action": "up"}, headers=_auth(service))
        assert response.status == 404
        assert (await response.json()) == {"error": "remote_ui_disabled"}
        assert injected == []
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_screen_rapid_requests_render_once(tmp_path: Path) -> None:
    """CPU protection: a fast-polling client must hit the encoded-PNG cache
    (minimum re-render interval) instead of re-rendering per request."""

    calls: list[int] = []
    frame = _lcd_frame()

    def _count_and_render() -> Image.Image:
        calls.append(1)
        return frame

    _, service = _make_service(tmp_path, screen_provider=_count_and_render)
    client = await _start_client(service)
    try:
        first = await client.get("/v1/screen", headers=_auth(service))
        second = await client.get("/v1/screen", headers=_auth(service))
        assert first.status == 200
        assert second.status == 200
        assert (await first.read()) == (await second.read())
        assert len(calls) == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_screen_rerenders_after_min_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import instantlink_bridge.sync.server as sync_server

    monkeypatch.setattr(sync_server, "SCREEN_MIN_RENDER_INTERVAL_S", 0.0)
    calls: list[int] = []

    def _fresh_frame() -> Image.Image:
        calls.append(1)
        return _lcd_frame((0, len(calls), 0))

    _, service = _make_service(tmp_path, screen_provider=_fresh_frame)
    client = await _start_client(service)
    try:
        await client.get("/v1/screen", headers=_auth(service))
        await client.get("/v1/screen", headers=_auth(service))
        assert len(calls) == 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_screen_unchanged_frame_skips_reencode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An identical frame object (unchanged snapshot upstream) must reuse the
    cached PNG bytes instead of re-encoding."""

    import instantlink_bridge.sync.server as sync_server

    monkeypatch.setattr(sync_server, "SCREEN_MIN_RENDER_INTERVAL_S", 0.0)
    encodes: list[int] = []
    real_encode = sync_server._encode_png

    def _counting_encode(image: Image.Image) -> bytes:
        encodes.append(1)
        return real_encode(image)

    monkeypatch.setattr(sync_server, "_encode_png", _counting_encode)
    frame = _lcd_frame()
    provider_calls: list[int] = []

    def _same_frame() -> Image.Image:
        provider_calls.append(1)
        return frame

    _, service = _make_service(tmp_path, screen_provider=_same_frame)
    client = await _start_client(service)
    try:
        await client.get("/v1/screen", headers=_auth(service))
        await client.get("/v1/screen", headers=_auth(service))
        assert len(provider_calls) == 2
        assert len(encodes) == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_screen_provider_failure_is_500(tmp_path: Path) -> None:
    def _boom() -> Image.Image:
        raise RuntimeError("render exploded")

    _, service = _make_service(tmp_path, screen_provider=_boom)
    client = await _start_client(service)
    try:
        response = await client.get("/v1/screen", headers=_auth(service))
        assert response.status == 500
        assert (await response.json()) == {"error": "screen_render_failed"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_input_injects_action(tmp_path: Path) -> None:
    injected: list[str] = []

    def _inject(action: str) -> bool:
        injected.append(action)
        return True

    _, service = _make_service(tmp_path, input_injector=_inject)
    client = await _start_client(service)
    try:
        response = await client.post("/v1/input", json={"action": "select"}, headers=_auth(service))
        assert response.status == 200
        assert (await response.json()) == {"ok": True, "action": "select"}
        assert injected == ["select"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_input_accepts_all_eight_actions(tmp_path: Path) -> None:
    injected: list[str] = []

    def _inject(action: str) -> bool:
        injected.append(action)
        return True

    _, service = _make_service(tmp_path, input_injector=_inject)
    client = await _start_client(service)
    try:
        actions = ["up", "down", "left", "right", "select", "back", "help", "pair"]
        for action in actions:
            response = await client.post(
                "/v1/input", json={"action": action}, headers=_auth(service)
            )
            assert response.status == 200
        assert injected == actions
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_input_invalid_action_is_400(tmp_path: Path) -> None:
    injected: list[str] = []

    def _inject(action: str) -> bool:
        injected.append(action)
        return True

    _, service = _make_service(tmp_path, input_injector=_inject)
    client = await _start_client(service)
    try:
        for body in ({"action": "jump"}, {"action": 7}, {"other": "up"}, {}):
            response = await client.post("/v1/input", json=body, headers=_auth(service))
            assert response.status == 400
            assert (await response.json())["error"] == "invalid_action"
        response = await client.post("/v1/input", data=b"not-json", headers=_auth(service))
        assert response.status == 400
        assert (await response.json())["error"] == "invalid_action"
        assert injected == []
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_input_without_injector_is_404(tmp_path: Path) -> None:
    _, service = _make_service(tmp_path)
    client = await _start_client(service)
    try:
        response = await client.post("/v1/input", json={"action": "up"}, headers=_auth(service))
        assert response.status == 404
        assert (await response.json()) == {"error": "remote_ui_unavailable"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_input_rejected_by_injector_is_400(tmp_path: Path) -> None:
    _, service = _make_service(tmp_path, input_injector=lambda action: False)
    client = await _start_client(service)
    try:
        response = await client.post("/v1/input", json={"action": "up"}, headers=_auth(service))
        assert response.status == 400
        assert (await response.json()) == {"error": "input_rejected"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_remote_ui_routes_fire_activity_callback(tmp_path: Path) -> None:
    """The auth middleware wraps every route, so the virtual-LCD endpoints
    must count as client activity with no extra plumbing."""

    calls: list[int] = []
    _, service = _make_service(
        tmp_path,
        client_activity_callback=lambda: calls.append(1),
        screen_provider=_lcd_frame,
        input_injector=lambda action: True,
    )
    client = await _start_client(service)
    try:
        await client.get("/v1/screen", headers=_auth(service))
        assert len(calls) == 1
        await client.post("/v1/input", json={"action": "back"}, headers=_auth(service))
        assert len(calls) == 2
        assert service.last_client_seen_monotonic is not None
    finally:
        await client.close()
