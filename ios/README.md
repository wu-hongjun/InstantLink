# InstantLink iOS app

The iOS companion for the **Bridge** (the Raspberry Pi appliance): pair once by
scanning a QR code on the Bridge LCD, then camera photos received by the Bridge
sync into the Photos library whenever this app is open nearby.

This is "the iOS app" in project terminology — distinct from **the App** (the
native macOS app under `macos/`). It shares no code with the App yet.

Implements phase **B1** of `docs/plans/050-iphone-auto-sync.md` (onboarding +
sync pull + save to Photos), plus the foreground auto-poll loop from B2.

## Status: builds clean, unit-tested in the simulator

The project builds warning-free with Xcode 26 and the pure logic (pairing URL
parsing, sync API models, SyncClient HTTP behavior, pairing persistence) is
covered by unit tests that run in the iOS simulator. The end-to-end flows
(hotspot join, Bonjour discovery against real hardware, Photos save,
camera-in-the-loop) still need the on-device checklist below with a physical
Bridge and iPhone.

## Generating the project

There is no checked-in `.xcodeproj`; it is generated from `project.yml` with
[XcodeGen](https://github.com/yonaskolb/XcodeGen):

```sh
brew install xcodegen
cd ios
xcodegen generate
open InstantLink-iOS.xcodeproj
```

Requirements: Xcode 16+ (iOS 17 SDK), Swift 5.9+. No third-party package
dependencies.

## Running the tests

The `InstantLink-iOSTests` unit-test target (defined in `project.yml`, hosted
in the app) covers PairingInfo parsing, the sync API model decoding against
the Bridge's exact JSON, SyncClient behavior (bearer auth, 401 mapping, Range
resume, restart-on-200, sha256 verification, ack) via an in-process
`URLProtocol` stub, and PairingStore persistence/pruning. No Bridge or network
is needed; everything runs in the simulator:

```sh
cd ios
xcodegen generate
xcodebuild test -project InstantLink-iOS.xcodeproj -scheme InstantLink-iOS \
  -destination 'platform=iOS Simulator,name=iPhone 17' CODE_SIGNING_ALLOWED=NO
```

(Substitute any simulator from `xcrun simctl list devices available`.) The
keychain-backed save/load round trip skips itself with a note if the test host
cannot use the keychain.

## Signing and entitlements

The app uses `NEHotspotConfiguration` to join the Bridge hotspot, which
requires the **Hotspot Configuration** capability
(`com.apple.developer.networking.HotspotConfiguration`, already wired in
`InstantLink/Resources/InstantLink.entitlements`).

- Select a development team in Xcode ▸ target ▸ Signing & Capabilities (or set
  `DEVELOPMENT_TEAM` in `project.yml` and regenerate).
- A paid Apple Developer team definitely supports the capability. Free
  personal teams may refuse to provision it — if automatic signing fails on
  the entitlement, that's why; test Same Wi-Fi mode (QR without `ssid`/`psk`,
  no entitlement needed at runtime) or use a paid team.
- Camera, local network, Bonjour (`_instantlink._tcp`), and add-only Photos
  usage strings are declared in `InstantLink/Resources/Info.plist`.

## Layout

```
ios/
  project.yml                        XcodeGen spec (app target InstantLink-iOS + unit tests, iOS 17.0)
  InstantLink/
    InstantLinkApp.swift             @main; RootView switches onboarding <-> sync on pairing
    Models/
      PairingInfo.swift              instantlink://pair QR payload parsing + validation
      SyncModels.swift               Codable shapes for the Bridge sync HTTP API
    Services/
      HotspotJoiner.swift            NEHotspotConfiguration join/forget (persistent, not joinOnce)
      BridgeBrowser.swift            NWBrowser _instantlink._tcp discovery -> host:port
      SyncClient.swift               URLSession client: status/queue/photo(Range resume)/ack
      PhotoSaver.swift               PHPhotoLibrary add-only save (original filename + capture date)
      PairingStore.swift             Keychain token + UserDefaults pairing/synced-id persistence
    ViewModels/
      SyncViewModel.swift            @MainActor orchestration: onboarding pipeline + poll loop
    Views/
      OnboardingView.swift           QR scan (AVFoundation) or manual pairing-link entry
      SyncView.swift                 status card, live transfer list, synced count, Sync now
      SettingsView.swift             pairing details, re-pair, forget bridge
    Resources/
      Info.plist                     usage strings, NSBonjourServices, ATS local networking
      InstantLink.entitlements       Hotspot Configuration
  InstantLinkTests/
    PairingInfoTests.swift           pairing URL parsing/validation
    SyncModelsTests.swift            Bridge JSON decoding fixtures
    SyncClientTests.swift            HTTP behavior via a URLProtocol stub
    PairingStoreTests.swift          synced-id persistence + pruning
```

## How it works

1. **Onboard** — scan the QR from the Bridge LCD:
   `instantlink://pair?v=1&device=IB-XXXX&host=192.168.8.1&port=8721&token=<hex>[&ssid=…&psk=…]`.
   If `ssid` is present, join that WPA2 network via `NEHotspotConfiguration`
   (persistent). Then browse Bonjour for `_instantlink._tcp` matching the
   device id, falling back to the QR's `host`, and verify the token against
   `GET /v1/status`. When the camera can't scan (broken camera, or the iOS
   simulator, which has none), "Enter pairing link instead" on the scanner
   screen accepts the same `instantlink://pair` URL pasted as text and drives
   the identical parse → join → discover → verify pipeline.
2. **Sync** — while foregrounded, every ~4 s: `GET /v1/queue`, skip ids already
   synced (persisted), then per item `GET /v1/photos/{id}` (resuming partial
   downloads with a `Range` header, verifying `sha256`), save to Photos
   (add-only), `POST /v1/photos/{id}/ack`. All requests carry
   `Authorization: Bearer <token>`. Backgrounding pauses the loop — sync is
   foreground-only in v1 by design (see the plan and
   `docs/research/wifi-aware-iphone-feasibility.md`).
3. **Transport** — plain HTTP on `:8721`; the WPA2 hotspot provides link-layer
   encryption. TLS with a pinned self-signed certificate is a v1.5 hardening
   item.

## Contract with the Bridge (phase A)

`Models/SyncModels.swift` matches the phase A implementation in
`bridge/src/instantlink_bridge/sync/` (as of the 2026-07-14 working tree —
phase A was uncommitted when this was written, so re-check on first build):

- `GET /v1/status` → `{"device", "proto", "outbox_depth"}`
- `GET /v1/queue` → `{"items": [{"item_id", "file_name", "size_bytes",
  "sha256", "received_at" (epoch seconds), "source_remote_ip"}]}`
- `GET /v1/photos/{item_id}` → bytes, supports `Range`
- `POST /v1/photos/{item_id}/ack` → `{"ok": true}`; unknown ids → 404
  `{"error": "unknown_item"}`
- Bonjour TXT records: `device`, `proto`; service
  `InstantLink-<device>._instantlink._tcp.local.`

Asset creation dates come from each photo's own EXIF (Photos reads it at save
time), not from `received_at`.

## On-device test checklist (manual, from plan 050)

Do these on a real iPhone — none of this is simulator-testable end to end:

1. **Hotspot join tolerance (do this first).** Join the Bridge hotspot via the
   QR flow and stay on it for several minutes with no internet. iOS marks
   app-initiated `NEHotspotConfiguration` joins as expected-captive-less, but
   may still auto-drop aggressive no-internet networks — this is the plan's
   flagged early-B1 risk. Verify the connection survives an idle period and a
   multi-photo sync.
2. QR scan → join → discover → paired, end to end from a factory-reset app.
3. Bonjour discovery on the hotspot **and** in Same Wi-Fi mode (QR without
   `ssid`); confirm the QR-host fallback works when mDNS is blocked.
4. Local network permission prompt appears once; verify behavior when denied
   (denial blocks even direct HTTP to the local address, not just Bonjour).
5. Camera-in-the-loop: camera FTP → Bridge outbox → photo lands in the Photos
   library with the right filename and capture date; ack deletes the spool
   file on the Bridge; camera C1 → print flow unchanged.
6. Resume: kill Wi-Fi (or walk away) mid-download of a large file, come back,
   verify the transfer resumes via `Range` and the sha256 check passes.
7. Duplicate suppression: force-quit after save-but-before-ack, relaunch,
   verify the item is re-acked (or at worst re-saved once) and never loops.
8. Background/foreground: backgrounding pauses polling; foregrounding resumes;
   screen stays awake during an active transfer.
9. Photos add-only permission denied path shows a usable error.
10. Forget bridge: token, Wi-Fi configuration, and synced-id history are gone;
    re-pairing from Settings works.

## Known gaps / open items

- ~~First compile pass: expect small fixes.~~ Resolved — builds warning-free
  with Xcode 26.
- ~~`SyncClient.downloadPhoto` iterates the response byte-by-byte
  (`URLSession.AsyncBytes`).~~ Resolved — the body now streams to disk in
  whole `Data` chunks via a per-task `URLSessionDataDelegate` with watermark
  backpressure; Range resume and streamed sha256 verification are unchanged
  (covered by `SyncClientTests`). Still worth a throughput sanity check on
  device with a 100 MP file.
- Per-photo thumbnails in the transfer list after save (plan B2 polish).
- ~~Skipped-because-already-synced items are never pruned from
  UserDefaults.~~ Resolved — `PairingStore` caps the persisted history at the
  most recent 5000 ids, pruned oldest-first in insertion order.
- No app icon or launch styling yet.
- Update the terminology table in the repo `CLAUDE.md` ("the iOS app") when
  this lands, per the plan.

---

Copyright 2026. Part of the InstantLink project.
