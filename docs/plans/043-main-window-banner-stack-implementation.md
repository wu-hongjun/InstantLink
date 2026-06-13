# 043 — Main Window Banner Stack Implementation (Phase 2 of 041)

Implements the direction proposed in `042-main-window-banner-stack-audit.md` (Move A + Move B together).

## Decisions locked in

1. Keep `updateError`, `updateAvailable`, `isUpdating`, `statusMessage`, `bridgeSnapshot` as separate ViewModel state. Resolve precedence at the view layer only. No ViewModel state refactor.
2. Auto-trust event reuses `statusMessage` with tone `.success`. Drop the shield-icon distinction.
3. `BridgeDiscoveryBanner.disconnectedStrip` deleted entirely. Bridge connection state remains visible via `BridgeConnectionIndicator` and the BridgeControl window.
4. Scope: Move A (precedence) + Move B (Bridge surface reassignment) ship together.

## Changes

### New: `macos/InstantLink/Features/Main/BannerStrip.swift`

Single shared SwiftUI component. API:

```swift
struct BannerStrip: View {
    enum Tone { case info, success, warning, error, accent }
    let tone: Tone
    let icon: String
    let text: String
    var progress: Double? = nil          // for "downloading update"
    var primaryButton: Button? = nil
    var dismissButton: Button? = nil
    
    struct Button { let label: String; let action: () -> Void; var prominent: Bool = false }
}
```

Internal tone → icon-color + background-color map mirrors the current values (red/blue/green/orange/accent opacities). Layout matches the current banner shape (`.caption`, `.padding(.horizontal, 10).padding(.vertical, 6)`, top-edge transition).

### `macos/InstantLink/Features/Main/MainView.swift`

Replace lines 13–101 (the BridgeDiscoveryBanner + update banners + status banner stack) with a single `@ViewBuilder var bannerSection`. The body of `bannerSection` is an if/else-if cascade in precedence order:

1. `updateError` → BannerStrip(.error, icon: `exclamationmark.triangle`, dismiss)
2. `statusMessage` tone `.error` → BannerStrip(.error, icon: `xmark.octagon.fill`, dismiss if persistent)
3. `statusMessage` tone `.warning` → BannerStrip(.warning, icon: `exclamationmark.triangle.fill`, dismiss if persistent)
4. `isUpdating` (progress < 1.0) → BannerStrip(.info, icon: `arrow.down.circle`, progress: %)
5. `isUpdating` (progress ≥ 1.0) → BannerStrip(.info, icon: spinner — kept as inline ProgressView)
6. `updateAvailable` → BannerStrip(.info, icon: `arrow.up.circle.fill`, primary: "Update Now" prominent)
7. Bridge setup condition (found + medium ≠ usb + not paired) → BannerStrip(.accent, icon: `link.badge.plus`, primary: "Set up")
8. `statusMessage` tone `.info` / `.success` → BannerStrip(.info/.success, icon per tone, dismiss if persistent)
9. else → EmptyView()

Remove the `BridgeDiscoveryBanner` import/usage. Remove the inline `statusBannerIcon`/`statusBannerBackground` computed properties (subsumed by BannerStrip's tone map).

### `macos/InstantLink/Core/ViewModel.swift`

In the constructor's `bridgeSnapshotCancellable` sink, track the previous `lastAutoTrustEvent` and, when it transitions to a fresher non-nil value, call `showStatus(L("Bridge connected and authorized"), tone: .success)`. Otherwise leave the snapshot mirror unchanged.

```swift
var previousAutoTrustEvent: Date?
bridgeSnapshotCancellable = bridgeCoordinator.$snapshot
    .receive(on: DispatchQueue.main)
    .sink { [weak self] snapshot in
        guard let self else { return }
        if let event = snapshot.lastAutoTrustEvent,
           event != previousAutoTrustEvent {
            previousAutoTrustEvent = event
            self.showStatus(L("Bridge connected and authorized"), tone: .success)
        }
        self.bridgeSnapshot = snapshot
    }
```

### Delete: `macos/InstantLink/Features/Bridge/BridgeDiscoveryBanner.swift`

After Move A+B, no remaining caller. Delete the file.

### Locale strings: remove orphans

- `"Bridge disconnected"` — no longer used anywhere. Remove from all 12 `Localizable.strings`.
- `"InstantLink Bridge ready to set up"` — still used (inline in MainView via BannerStrip text). Keep.
- `"Bridge connected and authorized"` — still used (via the new `showStatus` call in ViewModel). Keep.

## Verification

- `bash scripts/build-app.sh 0.1.41` — Swift compile.
- Manual smoke: launch with no Bridge → no banner. Trigger a status message (e.g., disconnect printer) → see single banner. Trigger an update available → see single banner. Combined scenarios: status `.error` should win over `updateAvailable`.

## Out of scope (deferred)

- Tests around the precedence resolver. The conditions are simple boolean cascades; manual smoke is sufficient for v1. Add tests in a follow-up if the resolver grows.
- Animated transitions between banners when precedence changes (e.g., cross-fade). Current top-edge `.move + .opacity` is fine — SwiftUI handles same-position view replacement with the existing transition modifier.
- Showing a "queued" badge if multiple conditions are active. YAGNI.

## Next step

After this lands and the install verifies cleanly, move to Phase 3 (Image editor audit) by writing `044-image-editor-audit.md`.
