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
import io
import logging
import mimetypes
import re
import secrets
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web
from zeroconf import IPVersion
from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf

from instantlink_bridge.net.addresses import detect_ipv4_addresses_for_interface
from instantlink_bridge.sync.outbox import SyncOutbox

if TYPE_CHECKING:
    from PIL import Image

LOGGER = logging.getLogger(__name__)

SERVICE_TYPE = "_instantlink._tcp.local."
SYNC_PROTO_VERSION = 1
DEFAULT_CONTENT_TYPE = "image/jpeg"
# Re-detect advertised IPv4s on this cadence: registration can race the
# hotspot coming up at boot, and the user can switch Wi-Fi modes from
# Settings at runtime — a one-shot registration would keep advertising
# stale addresses either way.
ADVERTISE_REFRESH_INTERVAL_S = 30.0
# Virtual-LCD CPU guard (plan 054 phase A): a phone polling GET /v1/screen
# faster than this serves the cached PNG without touching the renderer —
# a tight curl loop must not peg the Zero 2 W. ~3 fps is the plan's target
# poll rate and stays comfortably inside the budget.
SCREEN_MIN_RENDER_INTERVAL_S = 0.3
# The 8 abstract UiActions (ui/models.py UiAction values). Kept as string
# literals so the sync layer never imports the UI controller stack.
REMOTE_INPUT_ACTIONS = frozenset({"up", "down", "left", "right", "select", "back", "help", "pair"})
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


def rotate_sync_token(path: Path) -> str:
    """Replace the sync bearer token with a freshly generated one.

    Rotation is the revocation story for a photographed pairing QR (plan
    051 P3.11): every previously paired iPhone loses access until it scans
    a QR carrying the new token. Deleting the file first funnels creation
    through :func:`load_or_create_sync_token` so format and permissions
    (0640) stay identical to first-boot provisioning.

    Note the running :class:`SyncService` enforces its in-memory copy —
    app.py restarts it after rotation so :meth:`SyncService.start` re-reads
    this file.
    """

    try:
        path.unlink()
    except FileNotFoundError:
        pass
    token = load_or_create_sync_token(path)
    LOGGER.info("sync.token_rotated path=%s", path)
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
        outbox_changed_callback: Callable[[int], None] | None = None,
        enable_zeroconf: bool = True,
        address_provider: Callable[[], list[str]] | None = None,
        screen_provider: Callable[[], Image.Image | None] | None = None,
        input_injector: Callable[[str], bool] | None = None,
        remote_ui_enabled: bool = True,
    ) -> None:
        self._outbox = outbox
        self._port = port
        self._device_id = device_id
        self._client_activity_callback = client_activity_callback
        # Virtual LCD (plan 054 phase A). Both callables are injected by
        # app.py so this module never imports the UI controller stack:
        # ``screen_provider`` returns the current 240x240 frame (rendered
        # from the live UiSnapshot; the SAME object while the snapshot is
        # unchanged, which keys the PNG cache below), ``input_injector``
        # feeds an action string into the controller's GPIO action queue
        # and must be called on the event loop.
        self._screen_provider = screen_provider
        self._input_injector = input_injector
        self._remote_ui_enabled = remote_ui_enabled
        # Encoded-PNG cache: serialized by the lock so concurrent pollers
        # never render twice; keyed by frame identity plus a minimum
        # re-render interval (SCREEN_MIN_RENDER_INTERVAL_S).
        self._screen_lock = asyncio.Lock()
        self._screen_cache_png: bytes | None = None
        self._screen_cache_frame: Image.Image | None = None
        self._screen_cache_at = 0.0
        # Invoked with the new outbox depth after a successful ack so the
        # LCD chip decrements as the iPhone drains the queue (plan 051
        # P1.2); the spool-add side notifies from app.py.
        self._outbox_changed_callback = outbox_changed_callback
        self._enable_zeroconf = enable_zeroconf
        self._address_provider = address_provider or _advertise_addresses
        self._advertised_addresses: list[str] = []
        self._token_path = token_path
        self._token = load_or_create_sync_token(token_path)
        self._last_client_seen: float | None = None
        self._runner: web.AppRunner | None = None
        self._zeroconf: AsyncZeroconf | None = None
        self._service_info: AsyncServiceInfo | None = None
        self._zeroconf_refresh_task: asyncio.Task[None] | None = None

    @property
    def token(self) -> str:
        """Return the bearer token clients must present."""

        return self._token

    @property
    def last_client_seen_monotonic(self) -> float | None:
        """Return ``time.monotonic()`` of the last authenticated request."""

        return self._last_client_seen

    async def start(self) -> None:
        """Bind the HTTP listener and register the Bonjour service.

        The bearer token is re-read from disk on every (re)start: the
        constructor's copy would otherwise pin the process to a token that
        :func:`rotate_sync_token` has already revoked — app.py's rotation
        flow is exactly a stop/start pair relying on this re-read (plan
        051 P3.11). File IO runs off the event loop.
        """

        if self._runner is not None:
            return
        self._token = await asyncio.to_thread(load_or_create_sync_token, self._token_path)
        runner = web.AppRunner(self.build_app())
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=self._port)
        await site.start()
        self._runner = runner
        LOGGER.info("sync.server_started port=%s device=%s", self._port, self._device_id)
        if self._enable_zeroconf:
            await self._register_zeroconf()
            self._zeroconf_refresh_task = asyncio.create_task(
                self._run_zeroconf_refresh(), name="sync-zeroconf-refresh"
            )

    async def stop(self) -> None:
        """Unregister Bonjour and shut the HTTP listener down."""

        if self._zeroconf_refresh_task is not None:
            self._zeroconf_refresh_task.cancel()
            try:
                await self._zeroconf_refresh_task
            except asyncio.CancelledError:
                pass
            self._zeroconf_refresh_task = None
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
        # Virtual LCD (plan 054 phase A). Behind the same auth middleware,
        # so every poll/input counts as client activity automatically.
        app.router.add_get("/v1/screen", self._handle_screen)
        app.router.add_post("/v1/input", self._handle_input)
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
        depth = await asyncio.to_thread(self._outbox.depth)
        LOGGER.info("sync.photo_acked item=%s outbox_depth=%s", item_id, depth)
        self._notify_outbox_changed(depth)
        return web.json_response({"ok": True})

    async def _handle_screen(self, request: web.Request) -> web.Response:
        """Serve the current LCD frame as PNG (virtual LCD, plan 054).

        Successful serves are deliberately not logged: at the ~3 fps poll
        rate a per-request log line would drown the journal.
        """

        if not self._remote_ui_enabled:
            LOGGER.info("sync.remote_ui_rejected reason=disabled endpoint=screen")
            return _remote_ui_disabled_response()
        provider = self._screen_provider
        if provider is None:
            LOGGER.info("sync.remote_ui_rejected reason=unwired endpoint=screen")
            return _remote_ui_unavailable_response()
        async with self._screen_lock:
            now = time.monotonic()
            if (
                self._screen_cache_png is not None
                and now - self._screen_cache_at < SCREEN_MIN_RENDER_INTERVAL_S
            ):
                return web.Response(body=self._screen_cache_png, content_type="image/png")
            try:
                frame = await asyncio.to_thread(provider)
            except Exception:
                LOGGER.exception("sync.screen_render_failed")
                return web.json_response({"error": "screen_render_failed"}, status=500)
            if frame is None:
                return _remote_ui_unavailable_response()
            if frame is not self._screen_cache_frame or self._screen_cache_png is None:
                self._screen_cache_png = await asyncio.to_thread(_encode_png, frame)
                self._screen_cache_frame = frame
            self._screen_cache_at = now
            return web.Response(body=self._screen_cache_png, content_type="image/png")

    async def _handle_input(self, request: web.Request) -> web.Response:
        """Inject one UiAction into the controller queue (virtual LCD)."""

        if not self._remote_ui_enabled:
            LOGGER.info("sync.remote_ui_rejected reason=disabled endpoint=input")
            return _remote_ui_disabled_response()
        injector = self._input_injector
        if injector is None:
            LOGGER.info("sync.remote_ui_rejected reason=unwired endpoint=input")
            return _remote_ui_unavailable_response()
        try:
            payload = await request.json()
        except Exception:
            payload = None
        action = payload.get("action") if isinstance(payload, dict) else None
        if not isinstance(action, str) or action not in REMOTE_INPUT_ACTIONS:
            return web.json_response(
                {"error": "invalid_action", "allowed": sorted(REMOTE_INPUT_ACTIONS)},
                status=400,
            )
        # Called inline (not via to_thread): the injector is loop-affine —
        # it put_nowait()s onto the controller's asyncio action queue.
        try:
            accepted = injector(action)
        except Exception:
            LOGGER.exception("sync.input_inject_failed action=%s", action)
            return web.json_response({"error": "input_failed"}, status=500)
        if not accepted:
            LOGGER.warning("sync.input_rejected action=%s", action)
            return web.json_response({"error": "input_rejected"}, status=400)
        LOGGER.info("sync.input_injected action=%s", action)
        return web.json_response({"ok": True, "action": action})

    def _notify_outbox_changed(self, depth: int) -> None:
        """Report a new outbox depth; guarded like the activity callback so
        a UI-side failure can never turn a successful ack into a 500."""

        if self._outbox_changed_callback is None:
            return
        try:
            self._outbox_changed_callback(depth)
        except Exception:
            LOGGER.exception("sync.outbox_changed_callback_failed depth=%s", depth)

    async def refresh_zeroconf(self) -> None:
        """Re-detect advertised addresses; register late or update in place.

        Called by the periodic refresh task, and safe to call directly. A
        boot-time race (hotspot not yet up) leaves the initial registration
        with a partial address set, and runtime Wi-Fi mode switches change
        it — both converge here.
        """

        if not self._enable_zeroconf:
            return
        try:
            addresses = self._address_provider()
        except Exception:
            LOGGER.warning("sync.zeroconf_address_lookup_failed", exc_info=True)
            return
        if not addresses:
            # Keep advertising the last-known-good set rather than dropping
            # the registration during a transient interface flap.
            return
        if self._zeroconf is None:
            await self._register_zeroconf()
            return
        if addresses == self._advertised_addresses:
            return
        info = self._build_service_info(addresses)
        try:
            await self._zeroconf.async_update_service(info)
        except Exception:
            LOGGER.warning("sync.zeroconf_update_failed", exc_info=True)
            return
        LOGGER.info(
            "sync.zeroconf_addresses_updated previous=%s current=%s",
            ",".join(self._advertised_addresses),
            ",".join(addresses),
        )
        self._service_info = info
        self._advertised_addresses = addresses

    async def _run_zeroconf_refresh(self) -> None:
        while True:
            await asyncio.sleep(ADVERTISE_REFRESH_INTERVAL_S)
            await self.refresh_zeroconf()

    def _build_service_info(self, addresses: list[str]) -> AsyncServiceInfo:
        return AsyncServiceInfo(
            SERVICE_TYPE,
            f"InstantLink-{self._device_id}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(address) for address in addresses],
            port=self._port,
            properties={"device": self._device_id, "proto": str(SYNC_PROTO_VERSION)},
            server=f"InstantLink-{self._device_id}.local.",
        )

    async def _register_zeroconf(self) -> None:
        try:
            addresses = self._address_provider()
        except Exception:
            LOGGER.warning("sync.zeroconf_address_lookup_failed", exc_info=True)
            return
        if not addresses:
            LOGGER.warning("sync.zeroconf_skipped reason=no_ipv4_address")
            return
        info = self._build_service_info(addresses)
        zeroconf: AsyncZeroconf | None = None
        try:
            zeroconf = AsyncZeroconf(ip_version=IPVersion.V4Only)
            await zeroconf.async_register_service(info)
        except Exception:
            # Never let discovery failures take the HTTP service down; the
            # refresh task retries registration.
            LOGGER.warning("sync.zeroconf_register_failed", exc_info=True)
            if zeroconf is not None:
                try:
                    await zeroconf.async_close()
                except Exception:
                    LOGGER.debug("sync.zeroconf_close_failed", exc_info=True)
            return
        self._zeroconf = zeroconf
        self._service_info = info
        self._advertised_addresses = addresses
        LOGGER.info(
            "sync.zeroconf_registered service=%s addresses=%s port=%s",
            info.name,
            ",".join(addresses),
            self._port,
        )


def _unknown_item_response(item_id: str) -> web.Response:
    return web.json_response({"error": "unknown_item", "item_id": item_id}, status=404)


def _remote_ui_disabled_response() -> web.Response:
    return web.json_response({"error": "remote_ui_disabled"}, status=404)


def _remote_ui_unavailable_response() -> web.Response:
    return web.json_response({"error": "remote_ui_unavailable"}, status=404)


def _encode_png(image: Image.Image) -> bytes:
    """Encode a PIL frame to PNG bytes (runs in a worker thread)."""

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _advertise_addresses() -> list[str]:
    """Return non-loopback IPv4 addresses to advertise over mDNS."""

    addresses: list[str] = []
    for interface in _ADVERTISE_INTERFACES:
        for address in detect_ipv4_addresses_for_interface(interface):
            if not address.startswith("127.") and address not in addresses:
                addresses.append(address)
    return addresses
