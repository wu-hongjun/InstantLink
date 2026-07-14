# Wi-Fi Aware / iPhone Accessory Feasibility (researched 2026-07-14)

Fact-checked research into making the Bridge (Raspberry Pi Zero 2 W) discoverable by
iPhone via Apple's [Wi-Fi Aware framework](https://developer.apple.com/documentation/WiFiAware)
(iOS 26+) so camera photos can auto-sync to an iOS app with zero manual network setup.

Every claim below survived 3-vote adversarial verification against primary sources
unless marked otherwise. Bottom line first.

## Verdict

**Native Wi-Fi Aware on the Pi Zero 2 W's onboard radio is blocked indefinitely.**
Three independent hard blockers, any one of which is fatal today:

1. **Apple requires more than the Linux stack has.** Apple's Accessory Design
   Guidelines (R29, 2026, Wi-Fi Aware chapter) require accessories to implement
   **Wi-Fi Aware Specification v4.0**, be **Wi-Fi Aware certified** (a Wi-Fi
   Alliance program), and support secure pairing with NIK caching, pairwise
   data/management-frame protection, and beacon protection. iOS 26 additionally
   mandates **encrypted NAN datapath (NDP)** with no API switch to disable it.
2. **Linux has no NAN datapath.** Mainline wpa_supplicant ships only NAN
   *Unsynchronized Service Discovery* (USD, since v2.11, July 2024). Synchronized
   NAN discovery only started merging into hostap/wireless-next in late 2025
   (targeting kernel ~6.18) and **explicitly excludes the datapath**. The first
   upstream NDP implementation was a January 2026 Intel **RFC**
   ([LWN 1053322](https://lwn.net/Articles/1053322/)) — not in any released kernel.
   NAN pairing (PASN) is likewise absent.
3. **No evidence of NAN in the Pi's chip.** Nothing attests NAN support in the
   BCM43436/CYW43436 firmware or the `brcmfmac` driver (medium confidence —
   inferred from absence of evidence plus the stack blocker above, which is
   chip-agnostic and high confidence).

**The nearest-term co-processor path is also blocked.** Espressif's ESP32/C5/C6
NAN stack supports only discovery + plaintext follow-up (interop claimed with
Android 8+ only). Tested empirically against Apple's sample app it fails
("Invalid time bitmap in Availability"). Encrypted NDP + NAN 4.0 pairing is
targeted for **ESP-IDF v6.1** (roadmap final 2026-07-31); as of June 2026 an
Espressif engineer confirmed "we still haven't reached iOS compatibility yet"
([esp-idf #16743](https://github.com/espressif/esp-idf/issues/16743)).

**Even with working Wi-Fi Aware, silent background sync is impossible on iOS.**
Wi-Fi Aware connections require the app to be *actively running*; they close on
suspension, idle connections are garbage-collected in minutes, and there is no
CoreBluetooth-style state restoration or accessory-initiated wake (confirmed by
Apple DTS on the dev forums). The UX ceiling is "open the app near the Bridge and
photos flow in" — which a conventional-Wi-Fi architecture can match.

## What Wi-Fi Aware would require (for the record)

| Requirement | Detail | Source |
|---|---|---|
| iPhone hardware/OS | iPhone 12+, iOS 26+ (iPad 10th gen+ etc.) | Apple framework docs |
| App entitlement | `com.apple.developer.wifi-aware` (`Publish`/`Subscribe`) | Entitlement docs |
| App Info.plist | `WiFiAwareServices` service declarations (missing/invalid ⇒ runtime crash) | Adopting Wi-Fi Aware guide |
| Pairing | Mandatory, via system UI only: **AccessorySetupKit** (recommended for hardware accessories; pairs BT + Wi-Fi Aware together) or DeviceDiscoveryUI | WWDC25 session 228 |
| Accessory spec | Wi-Fi Aware v4.0, WFA **certification**, secure pairing, encrypted NDP | Accessory Design Guidelines R29 ch. 56 |
| Connection model | Network framework over paired Wi-Fi Aware peers; foreground-bound | WWDC25 228, Apple forums thread 787570 |

## Recommended architecture (buildable today)

Conventional Wi-Fi + Bonjour, with zero-typing onboarding — same UX outcome as
Wi-Fi Aware for a foreground app (this section is engineering judgment
synthesized from the verified blockers; the alternatives themselves produced no
*disqualifying* findings):

1. **Onboarding**: QR code on the Bridge LCD (and/or BLE GATT later) carrying
   SSID + WPA2 PSK + pairing token. iOS app scans it and joins the Bridge
   hotspot programmatically via `NEHotspotConfiguration` — no Settings app, no
   typing.
2. **Discovery**: Bridge advertises `_instantlink._tcp` via mDNS/Bonjour on
   `wlan0`; iOS app browses with `NWBrowser`. Works both on the Bridge hotspot
   and in Same Wi-Fi mode.
3. **Transfer**: HTTP service on the Bridge; iOS app pulls originals
   (token-authed), acks per file, saves via `PHPhotoLibrary`. Foreground-driven,
   like every competing camera-companion app.
4. **Upgrade path (~2027)**: ESP32-C5/C6 Wi-Fi Aware co-processor + WFA
   certification + AccessorySetupKit onboarding. Re-evaluate after ESP-IDF v6.1
   ships and someone demonstrates real iOS 26 pairing + encrypted NDP.

Implementation plan: `docs/plans/050-iphone-auto-sync.md`.

## Key sources

- Apple Wi-Fi Aware framework: <https://developer.apple.com/documentation/WiFiAware>
- Entitlement: <https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.wifi-aware>
- WWDC25 "Supercharge device connectivity with Wi-Fi Aware" (session 228): <https://developer.apple.com/videos/play/wwdc2025/228/>
- Accessory Design Guidelines (R29): <https://developer.apple.com/accessories/Accessory-Design-Guidelines.pdf>
- hostap synchronized-NAN series (Oct 2025): <https://lists.infradead.org/pipermail/hostap/2025-October/043880.html>
- Intel NAN Data Path RFC (Jan 2026): <https://lwn.net/Articles/1053322/>
- wpa_supplicant NAN USD README: Android `external/wpa_supplicant_8` `README-NAN-USD`
- ESP-IDF iOS 26 incompatibility thread: <https://github.com/espressif/esp-idf/issues/16743>
- Apple DTS on background behavior: <https://developer.apple.com/forums/thread/787570>
