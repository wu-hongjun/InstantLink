# 045 — Desktop Disconnected-Printer Flow Audit

Exploration deliverable for the desktop App's "saved printer is offline" UX. No code changes — this maps surfaces, names the failure modes the user hit, and proposes a direction. Implementation lives in a follow-up (046).

## Repro

User reported: Pi is powered off, phone is off, printer is off. App shows "No printer connected." Clicking **Reconnect** appears to do nothing meaningful. There is no visible **Forget / Re-pair** affordance.

## Surfaces

- **`MainView.swift:79–177`** — the centerpiece. Branches the "no printer ready" hero region on three booleans:
  1. `viewModel.isPairing` → `PairingChecklistCard` + Cancel (lines 82–100)
  2. `viewModel.hasKnownPrinterTarget` → "No printer connected" headline, optional `Connection failed` subtitle (when `pairingRecoveryMode == .reconnectFallback`), checklist, **Reconnect** + **Switch Printer** buttons, optional `reconnectRecoverySummary` caption (lines 101–141)
  3. `viewModel.hasSearchedOnce` → "No printer found" + Try Again (lines 142–157)
  4. else → fresh "Connect to your printer" + Find Printer (lines 158–174)
- **`PrinterPickerSheet`** (`SettingsViews.swift:4–161`) — presented on `viewModel.showPrinterPicker`. Lists Saved Printers (tap to switch) and Nearby Printers (tap to pair). Has a re-scan button but no per-row Forget.
- **`SettingsView`** — the only place Forget lives. `SettingsViews.swift:490–531` shows a trash icon per saved printer; the confirmation dialog also points the user at **Open Bluetooth Settings** to clear the macOS bond.
- **`PrinterConnectionCoordinator.swift`**:
  - `startPairingLoop(...)` (line 202) — owns the scan/connect state machine.
  - `attemptConnection(...)` (line 473) — single connect attempt with `duration: 3` (3 s).
  - `enterReconnectFallback(...)` (line 567) — single 3 s rescan after a failed targeted reconnect; lands in `.reconnectFallback`.
  - `deleteProfile(...)` (line 162) — wipes the profile and, if the deleted printer was connected/selected, automatically calls `startPairingLoop(disconnectCurrentPrinter:)`. Forget-then-pair is already one chained call internally.
- **`ViewModel.swift`**:
  - `reconnectSelectedPrinterOrScan()` (line 613) — entry point the Reconnect button wires to. If there's a saved target, calls `startPairing()`; otherwise opens the picker + `scanNearby()`.
  - `deleteProfile(_:)` (line 532) — the only public Forget surface; lives behind the trash icon in Settings.
  - `showStatus / showError` (line 1964, 1985) — the global banner system (the same `BannerStrip` shipped in 043). Pairing failures do NOT call these.

## Findings

**F1. "Reconnect" produces ~6 s of spinner and then the same screen.** Click → `startPairingLoop` → 3 s targeted connect → fail → 3 s rescan → `pairingRecoveryMode = .reconnectFallback` → `isPairing = false`. The user is dropped back into the "No printer connected" view with a small "Connection failed" subtitle (`pairing_stage_connect_failed` → "Connection failed"). No banner, no toast. Subjectively reads as "the button does nothing."

**F2. No Forget escape on the Main view.** With a saved printer that genuinely won't come back online (battery dead, given away, bonded wrong device), the only path forward is Settings → Saved Printers → trash → confirm → Open Bluetooth Settings. Four clicks deep and the user has to discover the gear icon as the entry point. The complaint "no way I can forget and repair" is literal.

**F3. "Switch Printer" misnamed for the offline-printer scenario.** The Reconnect/Switch pair implicitly assumes a working OTHER printer exists. With one saved printer that's offline, "Switch" opens a picker that shows the same offline printer + (often) nothing nearby. Dead end. The button label promises an action that isn't available.

**F4. `reconnectRecoverySummary` is hidden in `.caption` text.** `ViewModel.swift:435–444` produces "No new printers found" / "found N printer(s)" — meaningful info — but it's rendered at line 137–140 as `.font(.caption).foregroundColor(.secondary)` below the buttons. Easy to miss. The "did the rescan find anything?" signal is the most actionable bit of feedback we generate, and it's whisper-quiet.

**F5. Dead conditional in `startPairingLoop`.** `PrinterConnectionCoordinator.swift:228–232`:
```swift
if disconnectCurrentPrinter || self.snapshot.isConnected {
    await self.ffi.disconnectPrinter()
} else {
    await self.ffi.disconnectPrinter()
}
```
Both branches do the same thing. The `disconnectCurrentPrinter` parameter (line 205) is plumbed from `deleteProfile` (line 193) but its only consumer is this no-op fork. Either the else-branch was meant to skip disconnect (safer, matches the parameter intent) or the whole if was meant to gate a single `disconnectPrinter()` call. Either way, the current shape is misleading.

**F6. `currentReconnectTarget()` evaluated twice with a silent mask.** `PrinterConnectionCoordinator.swift:238–239`:
```swift
if let reconnectTarget = self.currentReconnectTarget() {
    let target = self.currentReconnectTarget() ?? reconnectTarget
    ...
}
```
The second call is needless. If state changed between the two (other task mutated `selectedPrinter`/`printerName`/`profiles`), the second wins silently. Cosmetic but smells.

**F7. Failure feedback never goes through the global banner.** `PrinterConnectionCoordinator.swift` uses its own `emitStatus` channel only for the in-flow probe messages ("No printers found" / "found N"). It never calls `showStatus(_, tone: .warning)` on the ViewModel for a hard failure. The banner system added in 043 — which IS the standard way to surface error/warning state on Main — is bypassed for the one flow that needs it most.

**F8. The post-failure surface conflates "Connection failed" with "No printer connected".** The hero headline stays "No printer connected" (line 103) even after a targeted reconnect failed. The recovery target name is only shown as a small `.caption` (line 109–113), so the user doesn't see *which* printer just failed. Misses an opportunity to be specific: "Couldn't reach 'Living Room Mini'" is actionable; "No printer connected" is a state, not an event.

**F9. Single-attempt then bail.** `startPairingLoop` (line 238) for the has-saved-target branch is one shot — one `attemptConnection`, one fallback rescan, done. The fresh-pair branch (line 262) is an unbounded retry loop. The asymmetry is fine in principle (don't auto-retry the same dead address), but combined with F1 it means Reconnect's behavior is "I gave up after one try" — which is what makes it feel unresponsive. There's no escalation (try again in 5 s, then in 15 s) and no hint at the cause.

**F10. Bond-recovery semantics are buried in the Forget dialog.** `SettingsViews.swift:514–530` confirmation explains "Bluetooth Settings" is needed to fully forget — but the dialog text is in `L("delete_printer_bluetooth_message")` and only appears when the user goes through Settings. A user clicking Reconnect repeatedly might be fighting a stale BlueZ-style bond and have no way to discover that the OS-level pairing is the real culprit. The Main view never mentions Bluetooth at all.

## Proposed direction

Two passes. **Pass A** is the minimum to unbreak the user complaint. **Pass B** is the broader feedback polish that makes the failure state legible. Pass C is the dead-code cleanup that pays back F5/F6.

### Pass A — Forget escape on the Main view (minimum viable)

When `hasKnownPrinterTarget && !isPairing` and `pairingRecoveryMode == .reconnectFallback` (i.e., the user has just seen a reconnect fail), show a third **Forget Printer** button below the Reconnect/Switch row.

- Visual weight: `.bordered` (not `.borderedProminent`), `.controlSize(.large)`, `.foregroundColor(.red)` or `role: .destructive`.
- Action: a confirmation dialog (reuse the `L("delete_printer_confirm")` + `L("delete_printer_bluetooth_message")` strings already wired in SettingsViews.swift:507–530), then `viewModel.deleteProfile(printerName ?? selectedPrinter)`.
- After confirm: `deleteProfile` already chains into `startPairingLoop` (line 193), so the user lands directly in the fresh-scan UI — no further navigation required.

Why gate on `.reconnectFallback` rather than show always: avoids accidental Forget on the first "No printer connected" appearance (e.g., transient sleep/wake). The button appears only AFTER the user has personally observed a failure.

### Pass B — Failure feedback polish

- **B1**. Specific headline on failure. When in `.reconnectFallback`, replace "No printer connected" with `L("couldnt_reach_named_printer", reconnectRecoveryTargetDisplayName)` — concrete and tells the user which device failed.
- **B2**. Promote `reconnectRecoverySummary` to a banner. After a failed reconnect, call `showStatus(L("connect_failed_summary", target), tone: .warning, autoDismiss: false)`. Uses the BannerStrip system from 043. The current caption text can stay or be retired.
- **B3**. Mention Bluetooth as a possible cause. Add a one-line `Label` under the checklist (1.circle / 2.circle / 3.circle), visible only in `.reconnectFallback`: "If it still fails, Forget Printer and re-pair." Or a `4.circle` step "Open System Settings → Bluetooth if pairing seems stuck." Wires the user to the OS-level recovery path the Settings dialog already mentions.

### Pass C — Dead-code cleanup

- **C1**. Collapse the duplicate-branch `if` at `PrinterConnectionCoordinator.swift:228–232`. Decide what the original intent was. Two candidates:
  - "Only disconnect when something is actually connected, OR when the caller asked us to" → `if disconnectCurrentPrinter || self.snapshot.isConnected { await self.ffi.disconnectPrinter() }`.
  - "Always disconnect" → drop the `if` and the parameter.
  - The plumbing from `deleteProfile(line 193)` argues for the first reading: the caller knows whether the deleted printer was the connected one, and the original code likely meant to skip the FFI hop when not.
- **C2**. Single `currentReconnectTarget()` evaluation at line 238–239. Bind once, branch on the optional.

### Out of scope for this audit

- Reworking the picker sheet (F3) — would couple this with a broader Printers panel design.
- Adding `.refreshing` / exponential-backoff retry to the targeted-reconnect path (F9) — proper fix is its own design.
- The `attemptConnection` 3-second budget (line 475) — may be too short for cold BLE adverts; needs separate measurement.

## Open questions to decide before implementation

1. **Pass A only, or A + B together?** A alone solves the literal complaint ("no way to forget"). B makes the *whole* failure state legible — bigger win, more strings to translate.
2. **Should the Forget button appear ALWAYS in the disconnected state, or only after `.reconnectFallback`?** Always = simpler logic, user can always escape; only-after = avoids accidental Forget on transient disconnects (sleep/wake).
3. **Pass C in the same PR as A/B, or its own cleanup PR?** C is unrelated to the user-visible fix. Mixing means the diff is harder to revert; separating means a tiny follow-up commit.
4. **Forget confirmation copy — reuse the Settings strings, or write new ones for the Main-view path?** Reuse is cheap and translation-stable. Writing new lets us tune the wording ("Forget this printer and start fresh?" reads more recovery-shaped than "Delete printer?").

## Next step

Pick a scope (A only / A + B / A + B + C / different cut), then write `046-desktop-disconnected-printer-implementation.md` with concrete diffs.
