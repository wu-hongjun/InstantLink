# 050 — iPhone auto-sync from the Bridge (Wi-Fi Aware deferred)

## Why

Users who set up automatic FTP on their camera should be able to use the Bridge
as an automatic photo-sync widget for their iPhone — camera → Bridge → iPhone —
with no Mac in the loop, alongside (or instead of) the existing FTP-by-button →
Instax print flow.

The original ask was Apple **Wi-Fi Aware** (iOS 26) accessory discovery. Deep
research (2026-07-14, `docs/research/wifi-aware-iphone-feasibility.md`) found
that path **blocked indefinitely on the Pi Zero 2 W**:

- Apple requires Wi-Fi Aware v4.0 + WFA certification + **encrypted NAN
  datapath**; Linux has no NAN datapath at all (first upstream RFC Jan 2026),
  and nothing attests NAN in the Pi's BCM43436 firmware/`brcmfmac`.
- The ESP32-C5/C6 co-processor route is iOS-incompatible until at least
  ESP-IDF v6.1 (~mid/late 2026, unproven).
- Even working Wi-Fi Aware cannot do silent background sync on iOS — the app
  must be actively running. So a conventional-Wi-Fi design has the **same UX
  ceiling**: open the app near the Bridge, photos flow in.

This plan therefore ships the sync product on conventional Wi-Fi + Bonjour with
zero-typing onboarding, and keeps Wi-Fi Aware as a tracked hardware upgrade
path (§ Future).

## Product shape

- New **delivery destination** concept on the Bridge: `Print`, `iPhone`, or
  `Both` (Settings ▸ Print ▸ Auto print area gains a `Send to` row).
- Camera workflow unchanged: FTP-by-button (`C1`) or camera auto-FTP. The
  Bridge fans each received image out to the enabled destinations.
- iPhone workflow: scan a QR on the Bridge LCD once (join hotspot + pair), then
  whenever the InstantLink iOS app is open near the Bridge, pending photos sync
  into the Photos library automatically. **Originals** are synced (full-res
  camera JPEG/HEIF), not the Instax-processed output.
- Sync-only use (no printer paired, no film) must work: the Bridge becomes a
  standalone camera→iPhone sync widget.

## Architecture

```text
Camera ──FTP──▶ pyftpdlib ──▶ asyncio.Queue[ReceivedImage]   (existing)
                                   │
                                   ├─▶ print pipeline (existing, unchanged)
                                   │
                                   └─▶ SyncOutbox (new, spool on disk)
                                            │
                    mDNS _instantlink._tcp  │  HTTP :8721 (token auth)
                                            ▼
iPhone ── NEHotspotConfiguration join ──▶ NWBrowser discover ──▶ pull + ack
                                                                  │
                                                          PHPhotoLibrary save
```

Transport choices (v1):

- **Discovery**: `python-zeroconf` advertising `_instantlink._tcp.local.` with
  TXT records `deviceid`, `ver`, `proto=1`. Works on the Bridge hotspot and in
  Same Wi-Fi mode. (Avahi not required; keeps it in-process and testable.)
- **Transfer**: plain HTTP on `:8721` served by the bridge process (aiohttp or
  stdlib-based; decide in implementation — aiohttp is already-packaged on
  Trixie and async-native). Endpoints:
  - `GET  /v1/status` — bridge identity, outbox depth (also used as liveness)
  - `GET  /v1/queue` — pending item ids + metadata (name, size, sha256, taken-at)
  - `GET  /v1/photos/{id}` — file bytes (supports `Range` for resume)
  - `POST /v1/photos/{id}/ack` — iPhone confirms save; Bridge deletes spool file
  - All require `Authorization: Bearer <pair-token>`.
- **Security posture v1**: WPA2 hotspot gives L2 encryption; bearer token gates
  access. TLS with a pinned self-signed cert is a v1.5 hardening item, noted in
  the code. Token lives in `/etc/InstantLinkBridge/sync.token` (0640 `ib:ib`),
  generated at provision time like `hotspot.psk`.
- **Pairing/onboarding**: QR rendered on the 240×240 LCD encoding
  `instantlink://pair?ssid=…&psk=…&host=192.168.8.1&token=…&device=IB-XXXX`.
  iOS app scans → `NEHotspotConfiguration(ssid:psk:)` join → Bonjour confirm →
  stores token. In Same Wi-Fi mode the QR omits ssid/psk and the app skips the
  join step. BLE GATT onboarding is explicitly deferred (QR is one screen and
  zero new dependencies).

### Why pull (iPhone-initiated), not push

iOS cannot run a reachable listener in the background, and the app must be
foreground anyway (same constraint Wi-Fi Aware has). Pull with per-file ack
gives free resume, retries, and multi-iPhone support later; the Bridge stays a
plain HTTP server with a disk spool.

## Bridge changes (phase A)

New module `bridge/src/instantlink_bridge/sync/`:

- `outbox.py` — `SyncOutbox`: spool dir `/var/lib/InstantLinkBridge/sync-outbox/`,
  copies (hard-links where possible) the received original before the print
  pipeline consumes/deletes it; persists a small JSON index; enforces a disk
  budget (evict oldest-acked first, then oldest-unacked past 24 h — mirrors the
  existing disk-pressure policy in `ARCHITECTURE.md`).
- `server.py` — the HTTP service + zeroconf registration, started/stopped from
  `app.py` alongside the FTP service; only advertises while `sync` destination
  is enabled.
- `models.py` — typed items/events.

Integration points (grounded in current code):

- `app.py` dequeue loop (`app.py:265`): after `ui.image_received(...)`, fan out —
  if destination includes iPhone, `outbox.add(received)`; if it includes Print,
  run `handle_received_image(...)` as today. Destination `iPhone`-only skips the
  print path entirely.
- **FTP preflight gate** (`camera/ftp.py:352`, `_ftp_preflight_reply`): today it
  rejects STOR when no printer is paired / offline / no film. Make it
  destination-aware: when sync-only (or Both with printer unavailable but sync
  enabled), accept the upload and reply normally; only keep the printer gates
  when Print is the sole destination. The `501 Bridge not paired` copy must stop
  claiming a Mac is required.
- `config.py`: new `[sync]` section — `enabled` (derived from destination),
  `destination = "print" | "iphone" | "both"` (default `print`), `port = 8721`,
  `outbox_budget_mb`. Schema-driven settings sync (plan 039) means the manager
  API/schema (`manager/schema.py`) needs the same rows.
- UI (`ui/`):
  - Settings ▸ Print: new `Send to` adjustable row (options Print / iPhone /
    Both) via the existing `SETTINGS_BY_PAGE` + `setting_options` tables.
  - Settings ▸ Network: new `iPhone pairing` action row → new
    `UiMode.SYNC_PAIRING` screen rendering the QR (pure-PIL QR via `segno` or
    vendored minimal encoder; no network needed) + hint text. KEY2 exits.
  - Status surface: when destination includes iPhone, readiness (`Ready to
    print` gating in `ux-flows.md`) treats "FTP path visible + sync enabled" as
    ready even with no printer; top-bar/queue chips show outbox depth and
    "iPhone connected" (recent authed request within N s).
  - Sync activity counts as power activity (keeps the idle stages from killing
    the radio mid-transfer).
- i18n: add EN + `_ZH_HANS` strings for all new copy.

## iOS app MVP (phase B)

New top-level component `ios/InstantLink/` (SwiftUI, iOS 17+, Xcode project —
unlike the Mac app, iOS needs entitlements/signing so `swiftc`-only is not
practical):

- Onboard: QR scan (`DataScannerViewController` or AVFoundation) →
  `NEHotspotConfiguration` join (entitlement: Hotspot Configuration) → Bonjour
  browse (`NWBrowser`, local-network privacy string) → token check → paired.
- Sync screen: connect → `GET /v1/queue` → download with resume → save via
  `PHPhotoLibrary` (add-only permission) → ack. Progress list UI, per-photo
  thumbnails after save.
- Foreground-driven; keep-alive while syncing (`isIdleTimerDisabled` during
  active transfer). No background claims in v1.
- Terminology: this is "the iOS app" — update `CLAUDE.md` terminology table
  when it lands.

## Phases / milestones

- **A1** — `SyncOutbox` + config + queue fan-out + destination-aware FTP gate.
  Verifiable on-device with `curl` against `:8721` (no iOS app needed).
- **A2** — Settings rows, QR pairing screen, status-surface changes, i18n.
- **B1** — iOS app: onboarding + manual "Sync now" pull, save to Photos.
- **B2** — auto-sync loop while app open, resume, multi-session polish.
- **C** — hardening: TLS pinning, multi-iPhone tokens, Same Wi-Fi QR variant,
  BLE onboarding if QR proves insufficient.

Each phase ends with the standard bridge checks (`ruff`, `mypy`, `pytest`) plus
on-device verification per `docs/current-context.md`, and a camera-in-the-loop
test: camera auto-FTP → outbox → iPhone save, and camera C1 → print unchanged.

## Risks / open questions

- **Single-radio contention**: camera FTP upload and iPhone download share
  `wlan0` (hotspot AP, 2.4 GHz ch 6). Throughput is split but both are bursty;
  acceptable for v1. Measure; if painful, sync drains after uploads go idle.
- **iPhone loses internet on the Bridge hotspot**: expected; document in-app.
  `NEHotspotConfiguration` marks the join app-initiated so iOS tolerates the
  captive-less network, but iOS may still auto-drop aggressive no-internet
  networks — needs a real-device test early in B1.
- **Disk pressure on the 32 GB SD**: outbox budget + eviction covers it, but
  100 MP HIF bursts are large; budget default should be conservative (~2 GB).
- **aiohttp vs stdlib** server choice and QR library packaging on the offline
  Pi (must ride `requirements/constraints.txt` + offline-deps deploy path).
- **Sony auto-FTP cadence**: camera-side auto FTP transfers every shot; confirm
  the a7C II auto-upload setting plays well with the 100-deep queue and
  print-destination gating (sync-only should bypass the print queue entirely —
  it must not wait on `AWAITING_CONFIRM`).

## Future: Wi-Fi Aware upgrade path (not scheduled)

Tracked, not planned. Trigger to re-evaluate: **ESP-IDF v6.1 ships encrypted
NDP + NAN pairing and a community/first-party demo pairs with iOS 26**. Then:
ESP32-C5/C6 co-processor (esp-hosted or standalone NAN NIC), AccessorySetupKit
onboarding replacing the QR, WFA certification cost/benefit review for a
giftable product. The v1 sync protocol (outbox + HTTP pull + ack) is transport-
agnostic on purpose — Wi-Fi Aware would swap the discovery/join layer only.
