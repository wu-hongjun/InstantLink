# Bridge Sync HTTP API Reference

The Bridge exposes a small HTTP API that an iOS app (or any client) uses to
pull received camera photos and, on screenless SKUs, to drive the LCD
remotely. It is implemented by `SyncService`
(`bridge/src/instantlink_bridge/sync/server.py`) and runs only when the
`[sync]` destination includes `iphone` (i.e. `iphone` or `both`).

## Endpoint & discovery

| Item | Value |
|------|-------|
| Bind | `0.0.0.0:8721` (`[sync].port`) |
| Discovery | Bonjour `_instantlink._tcp.local.`, TXT `device`, `proto` |
| Advertised addresses | non-loopback IPv4 on `wlan0` + `usb0`, refreshed every 30 s |
| Protocol version | `1` (`proto` field) |

The service is reachable over any active IP transport: the Bridge hotspot
(`192.168.8.1`), Same Wi-Fi, or the USB gadget link (`192.168.7.1`).

## Authentication

Every endpoint requires `Authorization: Bearer <token>`, compared with
`hmac.compare_digest`. The token is 32 hex chars in
`/etc/InstantLinkBridge/sync.token` (0640), created on first use and
rotatable from **Settings ▸ Network ▸ Reset sync token** (which restarts the
service so the new token takes effect; all paired clients must re-pair).

Missing/invalid token → `401 {"error": "unauthorized"}` with
`WWW-Authenticate: Bearer`.

## Photo sync endpoints

| Method | Path | Response |
|--------|------|----------|
| `GET` | `/v1/status` | `{"device", "proto", "outbox_depth"}` |
| `GET` | `/v1/queue` | `{"items": [OutboxItem, …]}` oldest first |
| `GET` | `/v1/photos/{id}` | file bytes; `Range` / `206` supported for resume |
| `POST` | `/v1/photos/{id}/ack` | `{"ok": true}`; deletes the spool file |

`OutboxItem` fields: `item_id` (hex), `file_name`, `size_bytes`, `sha256`,
`received_at` (epoch seconds), `source_remote_ip`.

Unknown id → `404 {"error": "unknown_item", "item_id": …}`.

Typical pull loop: `GET /v1/queue` → for each item `GET /v1/photos/{id}`
(resume with `Range` if a partial exists) → verify `sha256` → save →
`POST /v1/photos/{id}/ack`. `Content-Type` on the download is guessed from
the file name (defaults to `image/jpeg`); note Sony writes HEIF as `.HIF`,
which clients must map to HEIF when saving.

## Virtual-LCD endpoints (plan 054)

Present only when `[sync].remote_ui = true` (default). They let a phone act
as the Bridge's screen on screenless SKUs — the same pure renderer that
drives the physical LCD.

| Method | Path | Response |
|--------|------|----------|
| `GET` | `/v1/screen` | current 240×240 frame as `image/png` |
| `POST` | `/v1/input` | `{"action": "<a>"}` → `{"ok": true, "action": "<a>"}` |

`action` ∈ `up, down, left, right, select, back, help, pair` — injected into
the same action queue as the physical joystick/keys, so all input handling
(settle window, power activity) applies.

Errors: `remote_ui = false` → `404 {"error": "remote_ui_disabled"}`; no
snapshot/injector wired → `404 {"error": "remote_ui_unavailable"}`; bad
action → `400 {"error": "invalid_action", "allowed": [...]}`; queue full →
`400 {"error": "input_rejected"}`; render failure → `500`.

`/v1/screen` is CPU-guarded on the Pi Zero 2 W: frames are memoized by
snapshot identity and re-rendered at most every ~0.3 s, so a fast-polling
client cannot peg the CPU.

## Security posture (v1)

The WPA2 hotspot provides L2 encryption and the bearer token gates access;
TLS with a pinned self-signed cert is a v1.5 hardening item. See
`docs/plans/050-iphone-auto-sync.md` and `051-sync-ux-audit.md` for the
threat model and token-rotation story.
