"""Tests for the /v1/config/schema/adjustments handler (plan 039)."""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from instantlink_bridge.config import AdjustmentsConfig, DatestampFormat
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
from instantlink_bridge.manager.schema import build_adjustments_schema
from instantlink_bridge.manager.update_flow import ManagerEnvironment
from instantlink_bridge.ui.settings import (
    BUILTIN_PRESET_NAMES,
    USER_PRESET_SLOT_NAMES,
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


def _make_app(
    tmp_path: Path,
    private_key: SigningPrivateKey,
    config_path: Path,
    *,
    request_id: str = "req-schema",
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


def _signed_headers(
    private_key: SigningPrivateKey,
    *,
    method: str,
    path: str,
    body: bytes = b"",
    timestamp: int = 1000,
    nonce: str = "nonce-schema-0001",
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


def _fields_by_key(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {cast(str, field["key"]): field for field in schema["fields"]}


# --- pure schema shape -----------------------------------------------------


def test_adjustments_schema_includes_all_dataclass_fields() -> None:
    """Every AdjustmentsConfig dataclass field has a matching schema entry."""

    schema = build_adjustments_schema()
    schema_keys = {cast(str, field["key"]) for field in schema["fields"]}
    dataclass_keys = {f.name for f in dataclasses.fields(AdjustmentsConfig)}
    missing = dataclass_keys - schema_keys
    assert not missing, (
        f"AdjustmentsConfig fields not represented in the schema: {sorted(missing)}"
    )


def test_adjustments_schema_preset_options_include_builtins_and_custom_slots() -> None:
    """Preset picker enumerates the 5 built-ins + 6 Custom slots = 11."""

    schema = build_adjustments_schema()
    preset = _fields_by_key(schema)["preset"]
    options = cast(list[dict[str, str]], preset["options"])
    values = [opt["value"] for opt in options]
    assert values == [*BUILTIN_PRESET_NAMES, *USER_PRESET_SLOT_NAMES]
    assert len(values) == 11


def test_adjustments_schema_datestamp_format_options_match_enum_members() -> None:
    """datestamp_format picker enumerates exactly the 5 DatestampFormat values."""

    schema = build_adjustments_schema()
    datestamp_format = _fields_by_key(schema)["datestamp_format"]
    options = cast(list[dict[str, str]], datestamp_format["options"])
    expected = [
        ("quartz_date", "Quartz Date"),
        ("olympus", "Olympus"),
        ("contax", "Contax"),
        ("modern", "Modern"),
        ("lab_print", "Lab Print"),
    ]
    actual = [(opt["value"], opt["label"]) for opt in options]
    assert actual == expected
    assert len(options) == len(list(DatestampFormat))


def test_adjustments_schema_declares_depends_on_for_datestamp_format() -> None:
    schema = build_adjustments_schema()
    datestamp_format = _fields_by_key(schema)["datestamp_format"]
    assert datestamp_format["depends_on"] == {"field": "datestamp", "value": True}


def test_adjustments_schema_declares_depends_on_for_watermark_text() -> None:
    schema = build_adjustments_schema()
    watermark_text = _fields_by_key(schema)["watermark_text"]
    assert watermark_text["depends_on"] == {"field": "watermark", "value": True}


def test_adjustments_schema_slider_ranges_and_displays() -> None:
    """Per-axis steps + display tokens match the photographic units.

    Steps were unified at 10 in an earlier pass and then specialised
    per axis so the slider snaps on natural increments — quarter
    stops for exposure (step=25 = 0.25 EV), 10 % / 10° for the
    others. Display tokens drive the LCD chip + Mac badge
    formatting, so a wrong token would render the value with the
    wrong unit suffix.
    """

    schema = build_adjustments_schema()
    fields = _fields_by_key(schema)

    saturation = fields["saturation"]
    assert saturation["type"] == "slider"
    assert saturation["range"] == {"min": -100, "max": 100, "step": 10}
    assert saturation["display"] == "signed_percent"

    sharpness = fields["sharpness"]
    assert sharpness["range"] == {"min": -100, "max": 100, "step": 10}
    assert sharpness["display"] == "signed_percent"

    exposure = fields["exposure"]
    assert exposure["range"] == {"min": -100, "max": 100, "step": 25}
    assert exposure["display"] == "signed_ev"

    hue = fields["hue"]
    assert hue["range"] == {"min": -100, "max": 100, "step": 10}
    assert hue["display"] == "signed_degrees"

    vignette = fields["vignette"]
    assert vignette["range"] == {"min": 0, "max": 100, "step": 10}
    assert vignette["display"] == "unsigned_percent"


# --- endpoint --------------------------------------------------------------


@pytest.mark.asyncio
async def test_adjustments_schema_endpoint_requires_signed_request(
    tmp_path: Path,
) -> None:
    private_key = _private_key()
    config_path = tmp_path / "config.toml"
    app = _make_app(tmp_path, private_key, config_path)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        response = await client.get("/v1/config/schema/adjustments")
        body = cast(dict[str, Any], await response.json())
        assert response.status == 401, body
        assert body["ok"] is False
        assert body["auth_required"] is True
        assert body["operation_id"] == "config_schema_adjustments"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_adjustments_schema_endpoint_returns_200_with_signed_request(
    tmp_path: Path,
) -> None:
    private_key = _private_key()
    config_path = tmp_path / "config.toml"
    app = _make_app(tmp_path, private_key, config_path)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        path = "/v1/config/schema/adjustments"
        response = await client.get(
            path,
            headers=_signed_headers(private_key, method="GET", path=path),
        )
        data = cast(dict[str, Any], await response.json())
        assert response.status == 200, data
        assert data["ok"] is True
        schema = cast(dict[str, Any], data["schema"])
        assert schema["section"] == "adjustments"
        assert schema["schema_version"] == 1
        assert schema == build_adjustments_schema()
    finally:
        await client.close()
