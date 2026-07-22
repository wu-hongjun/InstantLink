"""Tests for the /v1/config GET + PUT handlers."""

from __future__ import annotations

import hashlib
import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

import pytest
from aiohttp import web
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
from instantlink_bridge.manager.update_flow import ManagerEnvironment

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


def _make_app(
    tmp_path: Path,
    private_key: SigningPrivateKey,
    config_path: Path,
    *,
    request_id: str = "req-config",
) -> web.Application:
    env = ManagerEnvironment(
        install_root=tmp_path / "InstantLinkBridge",
        backups_dir=tmp_path / "backups",
    )
    return create_app(
        config_path=config_path,
        request_id_factory=lambda: request_id,
        auth_verifier=_verifier(tmp_path, private_key),
        environment=env,
    )


def signed_headers(
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


def _json_body(body: Mapping[str, Any]) -> bytes:
    return json.dumps(body).encode()


# --- GET /v1/config --------------------------------------------------------


@pytest.mark.asyncio
async def test_config_get_returns_defaults_when_no_config_file(tmp_path: Path) -> None:
    private_key = _private_key()
    config_path = tmp_path / "missing.toml"
    app = _make_app(tmp_path, private_key, config_path)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        path = "/v1/config"
        response = await client.get(
            path,
            headers=signed_headers(private_key, method="GET", path=path),
        )
        data = cast(dict[str, Any], await response.json())
        assert response.status == 200, data
        assert data["ok"] is True
        config = data["config"]
        # Default model is None → serialized as "auto".
        assert config["printer"]["model"] == "auto"
        # Cleartext FTP password is masked.
        assert "password" not in config["ftp"]
        assert config["ftp"]["password_set"] is False  # "change-me" sentinel masked.
        # Default UI surface ships as light/medium/en.
        assert config["ui"]["appearance"] == "light"
        assert config["ui"]["font_size"] == "medium"
        assert config["ui"]["language"] == "en"
        # Adjustments only exposes the user-editable bits.
        assert config["adjustments"]["watermark_text"] == ""
        assert config["adjustments"]["datestamp_format"] == "quartz_date"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_config_get_round_trips_loaded_toml(tmp_path: Path) -> None:
    private_key = _private_key()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[ftp]
mode = "peer"
host = "192.168.7.1"
hotspot_host = "192.168.8.1"
username = "camera"
password = "supersecret"

[printer]
model = "mini_link_3"
fit = "crop"
quality = 80
keepalive_interval_s = 30
search_interval_s = 30

[workflow]
auto_print_delay_s = "off"
allow_print_without_film = true

[power]
idle_poweroff_enabled = true
idle_poweroff_after_s = 7200

[ui]
appearance = "dark"
font_size = "large"
language = "zh-Hans"

[adjustments]
watermark_text = "hello"
datestamp_format = "olympus"
""",
        encoding="utf-8",
    )
    app = _make_app(tmp_path, private_key, config_path)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        path = "/v1/config"
        response = await client.get(
            path,
            headers=signed_headers(private_key, method="GET", path=path),
        )
        data = cast(dict[str, Any], await response.json())
        assert response.status == 200, data
        config = data["config"]
        assert config["ftp"]["mode"] == "peer"
        assert config["ftp"]["username"] == "camera"
        assert config["ftp"]["password_set"] is True
        # PrinterModel.MINI_LINK3 serializes as "mini_link3" (no underscore
        # before the 3) per the canonical enum in ble/models.py.
        assert config["printer"]["model"] == "mini_link3"
        assert config["printer"]["quality"] == 80
        assert config["workflow"]["auto_print_delay_s"] == "off"
        assert config["workflow"]["allow_print_without_film"] is True
        assert config["power"]["idle_poweroff_enabled"] is True
        assert config["ui"]["appearance"] == "dark"
        assert config["ui"]["language"] == "zh-Hans"
        assert config["adjustments"]["watermark_text"] == "hello"
        assert config["adjustments"]["datestamp_format"] == "olympus"
    finally:
        await client.close()


# --- PUT /v1/config --------------------------------------------------------


@pytest.mark.asyncio
async def test_config_put_applies_diff_and_persists_file(tmp_path: Path) -> None:
    private_key = _private_key()
    config_path = tmp_path / "config.toml"
    app = _make_app(tmp_path, private_key, config_path)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        diff = {
            "printer": {"quality": 90, "fit": "crop"},
            "workflow": {"allow_print_without_film": True},
        }
        body = _json_body({"config": diff})
        path = "/v1/config"
        response = await client.put(
            path,
            data=body,
            headers={
                **signed_headers(private_key, method="PUT", path=path, body=body),
                "Content-Type": "application/json",
            },
        )
        data = cast(dict[str, Any], await response.json())
        assert response.status == 200, data
        config = data["config"]
        assert config["printer"]["quality"] == 90
        assert config["printer"]["fit"] == "crop"
        assert config["workflow"]["allow_print_without_film"] is True
        # File is persisted on disk.
        assert config_path.exists()
        on_disk = tomllib.loads(config_path.read_text(encoding="utf-8"))
        assert on_disk["printer"]["quality"] == 90
        assert on_disk["printer"]["fit"] == "crop"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_config_put_rejects_invalid_quality_with_field_error(tmp_path: Path) -> None:
    private_key = _private_key()
    config_path = tmp_path / "config.toml"
    app = _make_app(tmp_path, private_key, config_path)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        body = _json_body({"config": {"printer": {"quality": 0}}})
        path = "/v1/config"
        response = await client.put(
            path,
            data=body,
            headers={
                **signed_headers(private_key, method="PUT", path=path, body=body),
                "Content-Type": "application/json",
            },
        )
        data = cast(dict[str, Any], await response.json())
        assert response.status == 422, data
        assert data["error_code"] == "config_validation_failed"
        assert "printer.quality" in data["error"]["details"]["field_errors"]
        # File was not written.
        assert not config_path.exists()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_config_put_rejects_unknown_section(tmp_path: Path) -> None:
    private_key = _private_key()
    config_path = tmp_path / "config.toml"
    app = _make_app(tmp_path, private_key, config_path)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        body = _json_body({"config": {"bogus_section": {"foo": "bar"}}})
        path = "/v1/config"
        response = await client.put(
            path,
            data=body,
            headers={
                **signed_headers(private_key, method="PUT", path=path, body=body),
                "Content-Type": "application/json",
            },
        )
        data = cast(dict[str, Any], await response.json())
        assert response.status == 422, data
        assert data["error_code"] == "config_validation_failed"
        assert "bogus_section" in data["error"]["details"]["field_errors"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_config_put_masked_password_leaves_value_unchanged(tmp_path: Path) -> None:
    private_key = _private_key()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[ftp]
mode = "hotspot"
host = "192.168.7.1"
hotspot_host = "192.168.8.1"
username = "ib"
password = "originalsecret"
""",
        encoding="utf-8",
    )
    app = _make_app(tmp_path, private_key, config_path)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        # Sending the masked sentinel must be a no-op on the password.
        body = _json_body({"config": {"ftp": {"username": "newuser", "password": "__MASKED__"}}})
        path = "/v1/config"
        response = await client.put(
            path,
            data=body,
            headers={
                **signed_headers(private_key, method="PUT", path=path, body=body),
                "Content-Type": "application/json",
            },
        )
        data = cast(dict[str, Any], await response.json())
        assert response.status == 200, data
        on_disk = tomllib.loads(config_path.read_text(encoding="utf-8"))
        assert on_disk["ftp"]["username"] == "newuser"
        assert on_disk["ftp"]["password"] == "originalsecret"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_config_put_collects_multiple_field_errors(tmp_path: Path) -> None:
    private_key = _private_key()
    config_path = tmp_path / "config.toml"
    app = _make_app(tmp_path, private_key, config_path)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        body = _json_body(
            {
                "config": {
                    "printer": {"quality": 9999, "keepalive_interval_s": -1.0},
                    "ui": {"appearance": "neon"},
                }
            }
        )
        path = "/v1/config"
        response = await client.put(
            path,
            data=body,
            headers={
                **signed_headers(private_key, method="PUT", path=path, body=body),
                "Content-Type": "application/json",
            },
        )
        data = cast(dict[str, Any], await response.json())
        assert response.status == 422, data
        details = data["error"]["details"]["field_errors"]
        expected = {"printer.quality", "printer.keepalive_interval_s", "ui.appearance"}
        assert expected <= details.keys()
    finally:
        await client.close()


# --- [sync] section (plan 050) ----------------------------------------------


@pytest.mark.asyncio
async def test_config_get_includes_sync_destination_default(tmp_path: Path) -> None:
    private_key = _private_key()
    config_path = tmp_path / "missing.toml"
    app = _make_app(tmp_path, private_key, config_path)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        path = "/v1/config"
        response = await client.get(
            path,
            headers=signed_headers(private_key, method="GET", path=path),
        )
        data = cast(dict[str, Any], await response.json())
        assert response.status == 200, data
        config = data["config"]
        # Only the destination is exposed; port/paths/budget are
        # provisioning-level and stay out of the settings surface.
        assert config["sync"] == {"destination": "print"}
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested_destination", "expected_destination"),
    [("iphone", "iphone"), ("both", "print")],
)
async def test_config_put_applies_sync_destination_and_preserves_provisioning(
    tmp_path: Path,
    requested_destination: str,
    expected_destination: str,
) -> None:
    private_key = _private_key()
    config_path = tmp_path / "config.toml"
    config_path.write_text("[sync]\nport = 9000\n", encoding="utf-8")
    app = _make_app(tmp_path, private_key, config_path)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        body = _json_body({"config": {"sync": {"destination": requested_destination}}})
        path = "/v1/config"
        response = await client.put(
            path,
            data=body,
            headers={
                **signed_headers(private_key, method="PUT", path=path, body=body),
                "Content-Type": "application/json",
            },
        )
        data = cast(dict[str, Any], await response.json())
        assert response.status == 200, data
        assert data["config"]["sync"]["destination"] == expected_destination
        on_disk = tomllib.loads(config_path.read_text(encoding="utf-8"))
        assert on_disk["sync"]["destination"] == expected_destination
        # Provisioning-level fields survive a destination-only diff.
        assert on_disk["sync"]["port"] == 9000
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_config_put_rejects_unknown_sync_destination(tmp_path: Path) -> None:
    private_key = _private_key()
    config_path = tmp_path / "config.toml"
    app = _make_app(tmp_path, private_key, config_path)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        body = _json_body({"config": {"sync": {"destination": "android"}}})
        path = "/v1/config"
        response = await client.put(
            path,
            data=body,
            headers={
                **signed_headers(private_key, method="PUT", path=path, body=body),
                "Content-Type": "application/json",
            },
        )
        data = cast(dict[str, Any], await response.json())
        assert response.status == 422, data
        assert data["error_code"] == "config_validation_failed"
        assert "sync.destination" in data["error"]["details"]["field_errors"]
        assert not config_path.exists()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_config_put_rejects_provisioning_sync_fields(tmp_path: Path) -> None:
    private_key = _private_key()
    config_path = tmp_path / "config.toml"
    app = _make_app(tmp_path, private_key, config_path)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        body = _json_body({"config": {"sync": {"port": 9999}}})
        path = "/v1/config"
        response = await client.put(
            path,
            data=body,
            headers={
                **signed_headers(private_key, method="PUT", path=path, body=body),
                "Content-Type": "application/json",
            },
        )
        data = cast(dict[str, Any], await response.json())
        assert response.status == 422, data
        assert data["error_code"] == "config_validation_failed"
        assert "sync.port" in data["error"]["details"]["field_errors"]
    finally:
        await client.close()
