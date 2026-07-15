# 052 — AccessorySetupKit one-tap Bridge pairing (iOS 18+)

## Why

Plan 050 shipped iPhone sync with QR onboarding: point the phone at the Bridge
LCD, scan `instantlink://pair?...`, join the hotspot, done. It works, but it is
a two-device dance (wake the Bridge screen, navigate to the QR, aim the phone),
and the iOS side pays two blanket privacy prompts (local network, plus camera
for the scanner). DJI/Sonos-class accessories do this with one tap instead:
open the app near the device → the system accessory picker pops with a branded
card → tap → paired.

That picker is **AccessorySetupKit** (ASK, iOS 18+). What it buys us:

- **One-tap pairing.** App foreground near the Bridge → `ASAccessorySession`
  picker shows an "InstantLink Bridge (IB-XXXX)" card with a product image →
  one tap authorizes and pairs. No LCD interaction, no camera, no typing.
- **Per-accessory privacy.** ASK scopes Bluetooth (and Wi-Fi) access to the
  picked accessory. No blanket "InstantLink would like to use Bluetooth"
  prompt, and the accessory appears in **Settings ▸ Accessories** with
  per-device rename/forget — the system owns the accessory lifecycle.
- **Future alignment.** ASK is Apple's designated pairing UI for Wi-Fi Aware
  accessories (§ Wi-Fi Aware convergence) — this is the stepping stone for the
  2027 co-processor path, not a detour.

Honest ceiling, stated up front: the AirPods-style popup that appears while the
app is **not** running is Apple-first-party only. Third-party ASK requires the
app to be foreground and to explicitly activate the picker. Our UX target is
"open the iOS app near the Bridge, tap once" — same foreground constraint the
whole sync product already has (plan 050 / the Wi-Fi Aware research).

QR and manual-link entry **remain** as first-class fallbacks: iOS 17 devices,
broken cameras, and ASK-off Bridges all keep working. ASK augments, never
replaces.

## Product shape

- User opens the iOS app (fresh install or Settings ▸ Add bridge) within BLE
  range of a powered Bridge with sync enabled. The system picker appears with
  the Bridge's card; one tap pairs.
- After the tap: the app reads the pairing payload over BLE GATT (same fields
  the QR carries today), then runs the **existing** pipeline unchanged —
  hotspot join → Bonjour discover → token verify → sync screen.
- Bridge side is zero-interaction: it advertises whenever sync is listening
  and `ble_pairing` is on. The LCD pairing screen gains one hint line: the QR
  plus "or pair from the InstantLink app".
- Settings ▸ Accessories shows "InstantLink Bridge"; removing it there revokes
  the app's BLE access (the app detects this via `ASAccessoryEvent` and falls
  back to its own forget flow).

## Discovery design

Two ASK descriptor options considered:

1. **BLE service-UUID advertisement (recommended primary).** The Bridge
   advertises a 128-bit InstantLink service UUID; the app's
   `ASDiscoveryDescriptor.bluetoothServiceUUID` matches it. Works regardless
   of Wi-Fi state — hotspot up or down, Same Wi-Fi mode, mid-provisioning —
   and BLE advertising is cheap on the radio. This is the only signal that
   also carries the pairing payload (GATT), so it must exist anyway.
2. **Wi-Fi SSID-prefix descriptor** (`ssidPrefix = "InstantLink-"` — the
   hotspot SSID format from `system_info.default_hotspot_ssid()`). Only valid
   while the hotspot is broadcasting (useless in Same Wi-Fi mode), and it
   cannot deliver the token — the phone would still need GATT or the QR.
   Keep as a **second display item evaluated in B1** (Apple's docs are
   ambiguous on AND/OR semantics when one descriptor sets both properties;
   don't bet the flow on it). Its real value is the Wi-Fi Aware convergence
   later, and declaring `WiFi` support in the plist now costs nothing.

**Decision: BLE descriptor is the v1 matching signal; SSID prefix is declared
but optional.**

### InstantLink pairing service UUID (new, generated 2026-07-15)

Following the Instax convention (`docs/reference/protocol.md`) of a base UUID
with the first block incremented per characteristic:

| Item | UUID |
|------|------|
| InstantLink Pairing Service | `a7a6cdd5-6228-4508-808e-121d76f324b1` |
| Pairing Payload Characteristic (encrypted read) | `a7a6cdd6-6228-4508-808e-121d76f324b1` |
| Reserved (future status/Wi-Fi Aware handoff) | `a7a6cdd7-6228-4508-808e-121d76f324b1` |

Document these in `docs/reference/protocol.md` next to the Instax UUIDs (new
"InstantLink Pairing Service" section) when A1 lands. Lowercase in code
identifiers, per repo convention.

## Architecture

```text
Bridge (peripheral, new)                    iPhone (iOS 18+)
  BlueZ LEAdvertisingManager1                 ASAccessorySession.showPicker
    adv: service a7a6cdd5-…, name              matches bluetoothServiceUUID
         "InstantLink-XXXX"          ──BLE──▶  branded card → user taps
  BlueZ GattManager1                          CBCentralManager (ASK-scoped)
    char a7a6cdd6-… [encrypt-read]   ◀─read──  connect → read triggers
    payload = instantlink://pair?...           Just Works bond → payload
                                                    │
                              existing plan-050 pipeline, unchanged:
                              PairingInfo parse → NEHotspotConfiguration join
                              → NWBrowser → token verify → pull/save/ack
```

Key decisions:

- **The GATT payload is the exact `instantlink://pair?...` URL string** the QR
  encodes (built by the same controller helper): `v`, `device`, `host`,
  `port`, `token`, plus `ssid`/`psk` only while the hotspot is active. One
  payload builder on the Bridge, one parser (`PairingInfo`) on iOS, for both
  QR and BLE. ~200 bytes; BlueZ serves long reads via read-blob automatically.
- **Security model:** the characteristic is flagged `encrypt-read`, so a read
  forces BLE pairing/bonding first. With no display/keyboard the Bridge is a
  Just Works pairer — that is exactly what the existing `NoInputNoOutput`
  agent (registered before first printer contact, `ble/agent.py`) negotiates,
  and it already handles *incoming* SMP requests; the adapter must also be
  `Pairable=true` while advertising (verify in the spike — the printer flow
  never needed it). Just Works has no MITM protection, so
  `encrypt-authenticated-read` is unreachable; the trust factor is
  **proximity + physical possession**, the same factor as photographing the
  QR screen. Revocation is the existing `Reset sync token` flow (plan 051
  P3.11) — rotation invalidates every previously read payload, BLE or QR.
  ASK's pairing tap is the user-consent gate on the phone side.
- **Advertise-when-ready:** the advertiser runs iff `[sync]` destination
  includes iPhone **and** the sync service is `listening` **and**
  `ble_pairing = true`. Never advertise a payload pointing at a dead port
  (same honesty rule the QR screen enforces, plan 051 P2.3).

## Gate 0 — central+peripheral coexistence spike (blocks everything)

The FFI (`libinstantlink_ffi.so` via btleplug) holds the adapter as a BLE
**central** to the Printer: persistent connection + 10 s keepalive polls. The
Pi Zero 2 W's BCM43436 is a single BLE 4.2 combo radio. BlueZ supports
concurrent central+peripheral roles in principle; whether *this* chip/firmware
does, under *our* FFI's connection pattern, is unproven.

On-device spike (throwaway script, `dbus_fast` — already a dependency):

1. Register an `LEAdvertisement1` (service UUID + local name) while the bridge
   service runs with a paired, online Printer. Confirm `RegisterAdvertisement`
   succeeds and the adv is visible from a phone (nRF Connect).
2. Let the keepalive run ≥ 10 minutes; confirm no printer disconnects, no
   btleplug errors, no watchdog trips.
3. Print a real photo while advertising; confirm transfer time is not
   materially degraded and the adv stays registered afterward.
4. iPhone bonds + reads an `encrypt-read` test characteristic while the
   printer connection is live.

**Fallback decision tree (pre-committed):**

- All pass → full design.
- Fails only under active print traffic → pause advertising during
  `PRINTING` (and optionally `IMAGE_RECEIVED`→`PRINT_COMPLETE`); pairing
  during a print is rare and the picker simply won't match for those seconds.
- Adapter cannot advertise while the central link exists at all → advertise
  only when no printer is connected (still covers the headline sync-only
  widget case, where the printer poll is stopped) and keep QR primary for
  both-mode; note it in README.
- `RegisterAdvertisement` unusable on this BlueZ/kernel combo → kill phase A,
  keep the ASK Wi-Fi descriptor as a discovery-only nicety, revisit with the
  Wi-Fi Aware co-processor hardware.

Record the outcome in `bridge/docs/current-context.md` before A1 starts.

## Bridge changes (phase A)

New module `bridge/src/instantlink_bridge/sync/ble_advertiser.py`:

- `BlePairingAdvertiser` — owns two `dbus_fast.service.ServiceInterface`
  object trees on the system bus, following the `ble/agent.py` pattern:
  - `LEAdvertisement1` (`org.bluez.LEAdvertisement1`): `Type="peripheral"`,
    `ServiceUUIDs=[pairing service]`, `LocalName="InstantLink-XXXX"` (BlueZ
    splits into scan response as needed), registered via
    `LEAdvertisingManager1.RegisterAdvertisement` on `/org/bluez/hci0`.
  - `GattService1` + `GattCharacteristic1` (payload char, flags
    `["encrypt-read"]`), registered via `GattManager1.RegisterApplication`.
    `ReadValue` returns the current pairing URL bytes — built per-read via the
    same payload callback the QR screen uses, so token rotation and
    hotspot/Same-Wi-Fi switches are reflected without re-registration.
- Lifecycle mirrors `SyncService`: started/stopped from `app.py` next to the
  sync service start/stop/apply paths, fire-and-forget with exception
  guarding, never delays `bridge.ready`, holds no BLE locks shared with the
  printer path. Stop = `UnregisterAdvertisement` + `UnregisterApplication`,
  tolerant of an already-dead bus.
- Sets `Pairable=true` on the adapter while active if the spike shows it is
  required; restores prior state on stop.

Config (`config.py` + `manager/schema.py`, plan-039 schema-driven sync):

- `[sync] ble_pairing = true | false` (default `true`). Effective only when
  the sync destination includes iPhone; the advertiser tracks the sync
  service state (`listening` → advertise, else stop).

UI (`ui/`):

- `SYNC_PAIRING` screen: add a one-line hint under the QR — "or pair from the
  app" (EN + zh-Hans). No new screens; ASK needs nothing shown on the Bridge.
- No new readiness states: advertising failures log
  (`sync.ble_advertise_failed`) and degrade silently to QR-only — the QR path
  is always available on that screen, so no honesty gap on the LCD.

Docs: `protocol.md` UUID section; `ux-flows.md` hint-line; note the security
model (encrypt-read + Just Works + rotation) in `sync/server.py`'s module
docstring or `bridge/docs/`.

## iOS changes (phase B)

**Deployment target decision: stay at iOS 17.0, dual-path.** ASK code is
gated `if #available(iOS 18, *)`; the QR/manual flow is the iOS 17 path and
the universal fallback. Rationale: the fallback must exist regardless (broken
camera → manual link already exists), so a hard 18 bump buys nothing except
dropping working devices. Revisit a bump when ASK becomes the dominant
observed path.

- **Info.plist**: `NSAccessorySetupKitSupports = [Bluetooth, WiFi]`;
  `NSAccessorySetupBluetoothServices = [a7a6cdd5-6228-4508-808e-121d76f324b1]`.
  Note the ASK interaction: once these keys exist, blanket
  `NSBluetoothAlwaysUsageDescription` prompts are replaced by per-accessory
  authorization for ASK-managed peripherals.
- **Picker flow** (`Services/AccessoryPairing.swift`, new):
  `ASAccessorySession.activate` → `showPicker` with one
  `ASPickerDisplayItem` (name "InstantLink Bridge", product image,
  `ASDiscoveryDescriptor` with `bluetoothServiceUUID`). Handle
  `ASAccessoryEvent` cases: `accessoryAdded` → proceed; `pickerDidPresent/
  Dismiss` → UI state; `accessoryRemoved` (Settings ▸ Accessories forget) →
  run the existing forget-bridge cleanup.
- **Product image asset (hard requirement).** The picker card needs a real
  1:1 image of the Bridge hardware (transparent-background render or photo of
  the enclosed unit). This is a physical-product photography/render task —
  schedule it with B1, it gates the picker looking shippable.
- **Post-pick handoff**: CBCentralManager (now scoped to the picked
  accessory) → retrieve/connect the peripheral → discover the pairing service
  → read `a7a6cdd6-…`. The read triggers the system Just Works bond (no PIN
  UI). Parse the bytes with the existing `PairingInfo` — from here the
  plan-050 pipeline is **unchanged**: `NEHotspotConfiguration` join (when
  `ssid` present) → `BridgeBrowser` → token verify → `PairingStore`.
- **Entitlement caveat (unchanged from 050/README):** hotspot join still
  requires the Hotspot Configuration capability, which free personal teams
  cannot provision. Paid team = true one-tap end-to-end. Free team = ASK
  discovery + payload read, then the existing manual-join screen (SSID/PSK
  from the payload, "I've joined — continue"). ASK does not launder the
  entitlement.
- Onboarding UI: iOS 18 shows "Pair automatically" (ASK) as the primary
  button with "Scan QR instead" secondary; iOS 17 shows the current scanner.

## Wi-Fi Aware convergence

Per `docs/research/wifi-aware-iphone-feasibility.md`, ASK is Apple's
designated pairing UI for Wi-Fi Aware accessories (WWDC25 session 228): the
same picker pairs Bluetooth and Wi-Fi Aware together. When the ~2027
ESP32-C5/C6 upgrade path unblocks (trigger: ESP-IDF v6.1 encrypted NDP + a
demonstrated iOS pairing), the app-side change is a descriptor swap in the
same `ASPickerDisplayItem` — the picker, the product image, the
Settings ▸ Accessories integration, and the post-pick handoff all carry over.
This plan is that stepping stone; nothing here is throwaway on the Wi-Fi
Aware timeline, and the plan-050 transport (outbox + HTTP pull + ack) already
swaps discovery/join layers by design.

## Phases / milestones

- **Gate 0** — coexistence spike on `riverps-rpi-zero-2w` (§ above). Output:
  go / degraded-mode / no-go decision recorded in
  `bridge/docs/current-context.md`. **No A/B work before this.**
- **A1** — `ble_advertiser.py` + `[sync] ble_pairing` config + manager schema
  row + app.py lifecycle wiring. Tests: unit tests with a mocked
  `dbus_fast` bus (the `ble/agent.py` test pattern) covering
  register/unregister, payload freshness across token rotation, and
  state-tracking (listening → advertise, unavailable → stop). On-device:
  `journalctl` shows registration; nRF Connect sees the adv + name.
- **A2** — GATT payload characteristic + `encrypt-read` security + pairing
  hint line + i18n + protocol.md UUID docs. On-device: unprovisioned iPhone
  bonds via nRF Connect, reads the URL, and the value changes after
  `Reset sync token`; printer keepalive stays green throughout.
- **B1** — iOS: plist keys, `AccessoryPairing` service, picker flow, product
  image, post-pick GATT read → `PairingInfo` handoff, dual-path onboarding
  UI. Simulator-testable: payload parsing reuse (existing `PairingInfoTests`
  extended for BLE-sourced bytes); picker/ASK is device-only.
- **B2 / field test** — extend the `ios/README.md` on-device checklist:
  1. ASK picker appears within ~10 s of opening the app near the Bridge;
     card shows name + image.
  2. One tap → bond → payload read → hotspot join → first photo synced,
     no prompts beyond the picker (paid team).
  3. Free-team build: picker + read work, manual-join screen prefilled.
  4. Settings ▸ Accessories: rename survives; remove → app detects
     `accessoryRemoved` and forgets cleanly; re-pair works.
  5. Token rotation on the Bridge → old app install fails auth → re-pair via
     picker succeeds.
  6. Coexistence in anger: pair a new iPhone while a print is in flight
     (or observe the documented degraded behavior).
  7. iOS 17 device: no picker, QR flow unchanged.

Each phase ends with the standard bridge checks (`ruff`, `mypy --strict`,
`pytest`, suite green) or the iOS simulator test suite, plus the on-device
items above per `bridge/docs/current-context.md` discipline.

## Risks / open questions

- **BLE central+peripheral coexistence** (the big one): single BCM43436
  radio, btleplug-held central link, keepalive every 10 s. Gate 0 exists
  because this can kill phase A outright; the fallback tree is pre-committed
  so a partial failure degrades instead of stalling.
- **BlueZ D-Bus API stability**: `LEAdvertisingManager1`/`GattManager1` are
  stable-ish but BlueZ 5.82 quirks (unregister races on shutdown, adv slots
  exhausted after crashes) are real; the advertiser must be idempotent and
  tolerant of `AlreadyExists`/`DoesNotExist` replies. `TimeoutStopSec=12`
  already exists for BLE shutdown wedges — the advertiser must not add new
  ones.
- **Just Works exposure**: any phone in range can bond and read the payload
  while advertising. Accepted: equivalent to photographing the QR; proximity
  is the factor, rotation is the revocation. If field feedback objects,
  option: advertise only while the LCD pairing screen is open (worse UX,
  strictly safer) behind the existing `ble_pairing` toggle.
- **ASK picker matching latency**: reports of multi-second discovery before
  the card shows; measure in B2 item 1 and tune the adv interval (min
  interval costs battery — the Bridge is battery-powered; pick interval
  after measuring, likely 250 ms–1 s range).
- **Descriptor AND/OR semantics** when combining `bluetoothServiceUUID` and
  `ssidPrefix` in one `ASDiscoveryDescriptor` — resolve empirically in B1;
  worst case ship BLE-only.
- **iOS 18 adoption cut**: dual-path keeps 17 alive; the cost is two
  onboarding code paths to test forever. Revisit target bump once ASK usage
  dominates.
- **Product image requirement**: needs a real render/photo of the enclosure;
  a placeholder makes the flagship UX look broken. Gates B1's shippability,
  not its code.
- **`Pairable=true` scope**: does flipping it adapter-wide affect the printer
  bond or invite stray pairing attempts? Verify in Gate 0 step 4; scope to
  advertising windows if concerning.
- **Adv payload budget**: 128-bit UUID (18 B) + flags leaves no room for the
  local name in the primary adv — confirm BlueZ puts `LocalName` in the scan
  response and that ASK still displays it (fallback: shorten to product-image
  card only; the card name comes from our `ASPickerDisplayItem` anyway).
