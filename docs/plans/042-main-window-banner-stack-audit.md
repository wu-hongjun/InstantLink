# 042 — Main Window Banner Stack Audit (Phase 2 of 041)

Exploration deliverable for Phase 2 of `041-app-ux-optimization`. No code changes here — this is the map + proposed direction.

## Inventory: banner-class surfaces at the top of `MainView`

The Main window's top region (above the connected header / pairing UI) stacks up to **three independent banner classes** in `MainView.swift:13–101`:

### 1. BridgeDiscoveryBanner (always rendered, often empty)

`Features/Bridge/BridgeDiscoveryBanner.swift` — switches on `bridgeSnapshot.discovery` + `pairing` + `lastAutoTrustEvent`.

| Strip | Trigger | Visual | Action |
|---|---|---|---|
| `autoTrustStrip` | USB auto-trust event ≤ 5 s ago | Green ✓ "Bridge connected and authorized" | none — transient 5 s toast |
| `setupStrip` | Bridge `.found` but not paired, medium ≠ USB | Accent "InstantLink Bridge ready to set up" + "Set up" button | opens BridgeControl window |
| `disconnectedStrip` | Bridge discovery = `.lost` | Gray "Bridge disconnected" | none — passive |
| `EmptyView()` | paired+present, searching, or USB auto-trust pending | — | — |

### 2. Update banners (mutually exclusive group)

In `MainView.swift:17–79`. Order: `updateError` > `isUpdating` > `updateAvailable`.

| Strip | Trigger | Visual | Action |
|---|---|---|---|
| Error | `viewModel.updateError != nil` | Red 0.15, ⚠ icon | "Dismiss" plain button |
| Downloading | `isUpdating`, progress < 1.0 | Blue 0.10, ⬇ icon + progress bar + % | none (background) |
| Installing | `isUpdating`, progress ≥ 1.0 | Blue 0.10, spinner | none (background) |
| Available | `updateAvailable != nil` | Blue 0.10, ⬆ icon | "Update Now" `.borderedProminent` |

### 3. statusMessage banner

`viewModel.statusMessage` + `statusMessageTone` + `isStatusMessagePersistent`. Auto-fade or persistent.

| Tone | Background | Icon |
|---|---|---|
| `.info` | Blue 0.10 | `info.circle` |
| `.success` | Green 0.12 | `checkmark.circle.fill` |
| `.warning` | Orange 0.14 | `exclamationmark.triangle.fill` |
| `.error` | Red 0.14 | `xmark.octagon.fill` |

Dismissible only when `isStatusMessagePersistent == true`.

## Findings

**F1. No coordination rule — up to 3 stacked banners.** All three classes are independent. Worst case (Bridge disconnect + Update available + connection-failed status) eats ~84 pt of vertical real estate before main content.

**F2. Color overlap creates ambiguity.** `updateError` (red 0.15) and status `.error` (red 0.14) are visually indistinguishable. Same for `updating` blue and status `.info` blue. If both fire, the user can't tell which is which.

**F3. Competing CTAs.** `setupStrip` ("Set up") and `updateAvailable` ("Update Now") are both `.bordered` / `.borderedProminent` buttons in adjacent strips. Two prominent CTAs stacked is a cognitive cost.

**F4. `disconnectedStrip` is passive but expensive.** Bridge dropping off shows a gray strip that says "Bridge disconnected" — informational, no action. The same fact is already encodable as a state on `BridgeConnectionIndicator` (the dot shown next to the connected header). Banner is redundant.

**F5. `autoTrustStrip` is a 5 s toast occupying the banner lane.** It pushes all content down for 5 s on every USB auto-trust event. A floating HUD-style overlay would communicate the same thing without disrupting layout.

**F6. Visual language is *almost* consistent.** All banners use `.caption`, top-edge transitions, and small horizontal/vertical padding. Differences are small (background opacities differ by 0.02–0.07, icon styles vary). They're close enough that a single shared `BannerStrip` component would tighten the system.

## Proposed direction (next plan / Phase 2 implementation)

Two complementary moves. Both are reversible and don't change information content, only delivery.

### Move A — Single `BannerStrip` component with precedence

Introduce one `BannerStrip` view, parameterized by `tone`, `icon`, `text`, `action?`, `dismiss?`. Move all three banner classes through it.

Then add a `bannerStackResolver` that picks **at most 1 visible banner** from the union, using this precedence (high → low):

1. updateError
2. statusMessage (tone `.error`)
3. statusMessage (tone `.warning`)
4. isUpdating (downloading/installing)
5. updateAvailable
6. BridgeDiscoveryBanner.setupStrip
7. statusMessage (tone `.info` / `.success`)

Banners that lose the resolution don't render. Rationale: 99 % of the time only one fires; on the rare overlap, the most actionable wins. If we need to surface a queued banner later (e.g. "update available" while a print error is showing), we can add a peek affordance — but YAGNI for now.

### Move B — Reassign two surfaces out of the banner lane

- `BridgeDiscoveryBanner.disconnectedStrip` → drop. The Bridge connection state is already visible on `BridgeConnectionIndicator` in the disconnected-printer view, and on the connected header's grouped controls. If we want it visible always, add a small status dot to the header rather than a top strip.
- `BridgeDiscoveryBanner.autoTrustStrip` → reuse the existing `statusMessage` (tone `.success`, 5 s auto-dismiss). One toast surface, not two parallel ones.

Result: the banner lane becomes a single-row surface that shows at most one current condition. Bridge auto-trust uses the existing status-message mechanism. Bridge disconnect becomes a header-level indicator.

## Out of scope for Phase 2

- Reworking the connected/pairing/disconnected layouts themselves (lines 102–269) — that's Phase 3-ish territory.
- The QueueStrip and MainActions surfaces at the bottom.
- The Bridge UI's own banner surfaces (handled by the Bridge UX track 037–040).

## Open questions to decide before implementation

1. Should `statusMessage` and update banners stay in separate ViewModel state, or should we collapse to a single `currentBannerCondition` enum that the ViewModel publishes? (Simpler for the resolver, but a wider refactor.)
2. For the auto-trust event: do we keep a *separate* visual treatment (green checkmark, distinct from status `.success`) or accept that the existing tone covers it?
3. Should `disconnectedStrip` be deleted entirely, or kept behind a debug toggle for Bridge devs? (I'd vote delete — Bridge devs can use the BridgeControl window's own state surface.)

## Next step

Pick a direction (Move A + B together, A only, or B only), then write `043-main-window-banner-stack-implementation.md` with concrete diffs.
