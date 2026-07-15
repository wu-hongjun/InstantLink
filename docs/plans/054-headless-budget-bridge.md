# 054 — Headless budget Bridge (no LCD HAT, phone-driven everything)

## Why

The Waveshare LCD HAT is ~$14 of a ~$95–125 BOM and the single biggest
assembly/enclosure complication (window, button clearance). A budget SKU that
"just works" with the iPhone as its face could ship cheaper and simpler —
if every job the screen+buttons do today has a remote equivalent.

Exploration verdict: **feasible with the pieces already planned.** The
runtime already supports `UiSurface.HEADLESS` (NullDisplay/NullInput), the
manager API already schema-syncs settings to companion apps (plan 039), and
plans 052/053 make BLE the pairing + wake plane. The one genuinely new idea
needed — and it's cheap — is the **virtual LCD**.

## The virtual LCD (user-approved approach: "rendering the square UI is fine")

`render_snapshot` is a pure function producing 240×240 PIL frames, and all
input is 8 abstract `UiAction`s. Two endpoints on the existing sync/manager
HTTP surface:

- `GET /v1/screen` → current frame as PNG (rendered on demand from the live
  snapshot; ~3 fps poll or long-poll on snapshot change; token-authed)
- `POST /v1/input {"action": "up|down|left|right|select|back|help|pair"}`

The iOS app shows the square frame pixel-doubled with a D-pad/key overlay
(or tap zones). Every existing screen — Settings, pairing QR, readiness,
errors, help — works unmodified on day one. No second settings UI to build
or keep in sync; the LCD SKU and the headless SKU run identical software.
(Native-feeling iOS settings can still come later via the plan-039 schema;
the virtual LCD is the floor, not the ceiling.)

## First-contact bootstrap (the real headless problem)

A factory-fresh headless Bridge must be reachable with no screen to show a
QR. Layered plan, all already-designed pieces:

1. **BLE (primary):** the plan-052 advertiser runs whenever unprovisioned
   (ignoring the destination gate); the ASK picker pops on the phone, the
   GATT payload carries hotspot credentials + token exactly as designed. This
   alone solves first contact for iOS 18+.
2. **Boxed QR card (fallback):** provisioning already derives the SSID from
   the machine-id and generates PSK/token — print the pairing QR on a card in
   the box (same `instantlink://pair` payload; works with the existing
   scanner + manual-link path, any iOS 17+).
3. **USB to a computer (service/recovery):** unchanged admin path.

Recovery without buttons: BLE stays available as a management channel even
if Wi-Fi config is broken (it is independent of wlan0 state); the X306
hardware power button survives; worst case is the existing SD reflash. A
"factory reset" GATT command (token-authed, confirm-on-phone) should ship
with the SKU to avoid reflash-for-config-mistakes.

## iPhone ↔ Bridge over USB (the user's direct question)

- iOS apps get **no raw USB access** (no iPhone DriverKit; MFi only) — but
  none is needed. The Pi's micro-USB gadget port enumerates as a CDC
  Ethernet device; **USB-C iPhones support USB Ethernet at the OS level**.
  Expected behavior: plug Pi data port ↔ iPhone, iOS shows an "Ethernet"
  section in Settings, DHCP hands the phone a `192.168.7.x` address, and the
  app reaches the same token-authed HTTP API (sync, virtual LCD, manager) as
  ordinary networking. Cable-config becomes "plug it in, open the app".
- **Empirical gate (10 minutes, hardware on hand):** connect the Pi gadget
  port to the iPhone Air; check Settings ▸ Ethernet appears; Safari to
  `http://192.168.7.1:8721/v1/status` → a 401 JSON body proves the whole
  chain. Record ECM vs NCM behavior and the iOS version. (The Sony-camera
  USB-host failure documented in bridge/docs does not predict iPhone
  behavior — the phone is a normal USB host like the Mac, which enumerates
  this gadget fine.)
- If the gate fails on ECM: try NCM gadget function (`g_ncm`/configfs) —
  Apple's own gadget driver preference — before declaring USB-to-iPhone dead.
  If it still fails, the SKU loses nothing essential: BLE + Wi-Fi cover all
  flows; USB stays a computer-only admin path.

## What the screen/buttons do today → headless equivalent

| Today (LCD HAT) | Headless |
|---|---|
| Pairing QR | ASK/BLE pairing (052); boxed QR card |
| Readiness/status/errors | App status card (data already in /v1/status + snapshot); Live Activity (053); virtual LCD |
| Settings (all) | Virtual LCD now; schema-driven native screens later (039 payload) |
| KEY3 printer pairing | Virtual LCD `pair` action; later a native "Find printer" button |
| Print preview/cancel window | Virtual LCD; or auto-print 0s default for this SKU |
| Boot splash / idle dim | n/a (no display; drop boot-splash unit + backlight rules from the image) |

## Build shape (when scheduled)

- **A — virtual LCD endpoints** on the bridge (screen PNG + input POST,
  token-authed, off-by-default `[sync] remote_ui` toggle; render throttling
  so a polling phone can't peg the Zero 2 W CPU). Small: the renderer and
  action queue already exist. Testable with curl immediately.
- **B — iOS remote-screen view** (image + D-pad; Settings ▸ Bridge screen).
- **C — headless image profile**: build/provision variant without HAT
  packages (luma/gpio stays installed but `ui.surface=headless`), BLE
  advertiser always-on when unprovisioned, factory-reset GATT command.
- **Gate:** the USB-to-iPhone experiment above, any time; and 052 Gate 0
  (radio coexistence) which this SKU depends on even more heavily.

## Risks

- BLE becomes a single point of first-contact failure on the budget SKU →
  boxed QR card is the mandatory analog backup.
- Virtual-LCD input latency over hotspot (fine) vs BLE-only situations (no
  transport for the screen — virtual LCD requires an IP link; acceptable:
  it's a settings surface, not a pairing surface).
- Supporting two SKUs: keep ONE software image; SKU difference is config +
  BOM only, or divergence will rot the budget path.
