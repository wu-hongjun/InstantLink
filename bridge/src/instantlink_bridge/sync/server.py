"""HTTP pickup service + Bonjour advertisement for the iOS app.

The iPhone pulls: it discovers the Bridge via ``_instantlink._tcp.local.``,
then drains the :class:`~instantlink_bridge.sync.outbox.SyncOutbox` over a
small bearer-token HTTP API. All outbox calls run via
:func:`asyncio.to_thread` because the outbox is synchronous.

Security posture (v1): the WPA2 hotspot provides L2 encryption and the
bearer token gates access. TLS with a pinned self-signed certificate is a
v1.5 hardening item.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import mimetypes
import re
import secrets
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import Path

from aiohttp import web
from zeroconf import IPVersion
from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf

from instantlink_bridge.net.addresses import detect_ipv4_addresses_for_interface
from instantlink_bridge.sync.outbox import SyncOutbox

LOGGER = logging.getLogger(__name__)

SERVICE_TYPE = "_instantlink._tcp.local."
SYNC_PROTO_VERSION = 1
DEFAULT_CONTENT_TYPE = "image/jpeg"
_TOKEN_PATTERN = re.compile(r"[0-9a-fA-F]{32}")
_ADVERTISE_INTERFACES = ("wlan0", "usb0")

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def load_or_create_sync_token(path: Path) -> str:
    """Load the sync bearer token, creating a fresh one if needed.

    The token is 32 hex characters (``secrets.token_hex(16)``). An existing
    file is stripped and validated; anything malformed is regenerated.
    """

    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    except OSError:
        LOGGER.warning("sync.token_read_failed path=%s", path, exc_info=True)
        existing = ""
    if _TOKEN_PATTERN.fullmatch(existing) is not None:
        return existing
    if existing:
        LOGGER.warning("sync.token_invalid_regenerating path=%s", path)
    token = secrets.token_hex(16)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{token}\n", encoding="utf-8")
    path.chmod(0o640)
    LOGGER.info("sync.token_created path=%s", path)
    return token


class SyncService:
    """Bearer-token HTTP API over the outbox, advertised via Bonjour."""

    def __init__(
        self,
        outbox: SyncOutbox,
        *,
        port: int,
        token_path: Path,
        device_id: str,
        client_activity_callback: Callable[[], None] | None = None,
        enable_zeroconf: bool = True,
    ) -> None:
        self._outbox = outbox
        self._port = port
        self._device_id = device_id
        self._client_activity_callback = client_activity_callback
        self._enable_zeroconf = enable_zeroconf
        self._token = load_or_create_sync_token(token_path)
        self._last_client_seen: float | None = None
        self._runner: web.AppRunner | None = None
        self._zeroconf: AsyncZeroconf | None = None
        self._service_info: AsyncServiceInfo | None = None

    @property
    def token(self) -> str:
        """Return the bearer token clients must present."""

        return self._token

    @property
    def last_client_seen_monotonic(self) -> float | None:
        """Return ``time.monotonic()`` of the last authenticated request."""

        return self._last_client_seen

    async def start(self) -> None:
        """Bind the HTTP listener and register the Bonjour service."""

        if self._runner is not None:
            return
        runner = web.AppRunner(self.build_app())
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=self._port)
        await site.start()
        self._runner = runner
        LOGGER.info("sync.server_started port=%s device=%s", self._port, self._device_id)
        if self._enable_zeroconf:
            await self._register_zeroconf()

    async def stop(self) -> None:
        """Unregister Bonjour and shut the HTTP listener down."""

        if self._zeroconf is not None:
            try:
                if self._service_info is not None:
                    await self._zeroconf.async_unregister_service(self._service_info)
                await self._zeroconf.async_close()
                LOGGER.info("sync.zeroconf_unregistered device=%s", self._device_id)
            except Exception:
                LOGGER.warning("sync.zeroconf_unregister_failed", exc_info=True)
            self._zeroconf = None
            self._service_info = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            LOGGER.info("sync.server_stopped port=%s", self._port)

    def build_app(self) -> web.Application:
        """Build the aiohttp application (exposed for in-process tests)."""

        @web.middleware
        async def auth_middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
            if not self._is_authorized(request):
                LOGGER.info(
                    "sync.request_unauthorized path=%s remote=%s",
                    request.path,
                    request.remote,
                )
                return web.json_response(
                    {"error": "unauthorized"},
                    status=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
            self._note_client_activity()
            return await handler(request)

        app = web.Application(middlewares=[auth_middleware])
        app.router.add_get("/v1/status", self._handle_status)
        app.router.add_get("/v1/queue", self._handle_queue)
        app.router.add_get("/v1/photos/{item_id}", self._handle_photo)
        app.router.add_post("/v1/photos/{item_id}/ack", self._handle_ack)
        return app

    def _is_authorized(self, request: web.Request) -> bool:
        header = request.headers.get("Authorization", "")
        scheme, _, candidate = header.partition(" ")
        if scheme != "Bearer":
            return False
        return hmac.compare_digest(candidate.strip().encode(), self._token.encode())

    def _note_client_activity(self) -> None:
        self._last_client_seen = time.monotonic()
        if self._client_activity_callback is None:
            return
        try:
            self._client_activity_callback()
        except Exception:
            LOGGER.exception("sync.client_activity_callback_failed")

    async def _handle_status(self, request: web.Request) -> web.Response:
        depth = await asyncio.to_thread(self._outbox.depth)
        return web.json_response(
            {
                "device": self._device_id,
                "proto": SYNC_PROTO_VERSION,
                "outbox_depth": depth,
            }
        )

    async def _handle_queue(self, request: web.Request) -> web.Response:
        items = await asyncio.to_thread(self._outbox.pending)
        return web.json_response({"items": [asdict(item) for item in items]})

    async def _handle_photo(self, request: web.Request) -> web.StreamResponse:
        item_id = request.match_info["item_id"]
        path = await asyncio.to_thread(self._outbox.path_for, item_id)
        if path is None or not path.is_file():
            return _unknown_item_response(item_id)
        item = await asyncio.to_thread(self._outbox.get, item_id)
        file_name = item.file_name if item is not None else path.name
        content_type = mimetypes.guess_type(file_name)[0] or DEFAULT_CONTENT_TYPE
        LOGGER.info("sync.photo_served item=%s file=%s", item_id, file_name)
        # FileResponse honors Range requests for resumable downloads and
        # keeps the preset Content-Type header.
        return web.FileResponse(path, headers={"Content-Type": content_type})

    async def _handle_ack(self, request: web.Request) -> web.Response:
        item_id = request.match_info["item_id"]
        acked = await asyncio.to_thread(self._outbox.ack, item_id)
        if not acked:
            return _unknown_item_response(item_id)
        return web.json_response({"ok": True})

    async def _register_zeroconf(self) -> None:
        addresses = _advertise_addresses()
        if not addresses:
            LOGGER.warning("sync.zeroconf_skipped reason=no_ipv4_address")
            return
        info = AsyncServiceInfo(
            SERVICE_TYPE,
            f"InstantLink-{self._device_id}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(address) for address in addresses],
            port=self._port,
            properties={"device": self._device_id, "proto": str(SYNC_PROTO_VERSION)},
            server=f"InstantLink-{self._device_id}.local.",
        )
        zeroconf: AsyncZeroconf | None = None
        try:
            zeroconf = AsyncZeroconf(ip_version=IPVersion.V4Only)
            await zeroconf.async_register_service(info)
        except Exception:
            # Never let discovery failures take the HTTP service down; the
            # next start() retries registration.
            LOGGER.warning("sync.zeroconf_register_failed", exc_info=True)
            if zeroconf is not None:
                try:
                    await zeroconf.async_close()
                except Exception:
                    LOGGER.debug("sync.zeroconf_close_failed", exc_info=True)
            return
        self._zeroconf = zeroconf
        self._service_info = info
        LOGGER.info(
            "sync.zeroconf_registered service=%s addresses=%s port=%s",
            info.name,
            ",".join(addresses),
            self._port,
        )


def _unknown_item_response(item_id: str) -> web.Response:
    return web.json_response({"error": "unknown_item", "item_id": item_id}, status=404)


def _advertise_addresses() -> list[str]:
    """Return non-loopback IPv4 addresses to advertise over mDNS."""

    addresses: list[str] = []
    for interface in _ADVERTISE_INTERFACES:
        for address in detect_ipv4_addresses_for_interface(interface):
            if not address.startswith("127.") and address not in addresses:
                addresses.append(address)
    return addresses
