# 046 — Desktop Disconnected-Printer Flow Implementation

Implementation of A + B + C from `045-desktop-disconnected-printer-audit.md`.

## Pass A — Forget Printer button on Main view

`macos/InstantLink/Features/Main/MainView.swift:124–141`

Add a third button below the Reconnect / Switch HStack, gated on `pairingRecoveryMode == .reconnectFallback` so it only appears after the user has personally observed a failure.

- Style: `.bordered`, `role: .destructive`, `.controlSize(.large)`.
- Wrap the HStack in a `VStack(spacing: 10)` so Forget sits on its own row (it's destructive — don't crowd it next to the primary action).
- Tap → opens a `.confirmationDialog` reusing the same strings already wired in `SettingsViews.swift:507–531`:
  - title: `L("delete_printer_confirm")`
  - body: `L("delete_printer_bluetooth_message")`
  - buttons: **Open Bluetooth Settings** (opens `x-apple.systempreferences:com.apple.BluetoothSettings`), **Delete** (destructive, calls `viewModel.deleteProfile(target)`), **Cancel**.
- Target resolution: `viewModel.printerName ?? viewModel.selectedPrinter ?? viewModel.pairingRecoveryTarget`.
- `deleteProfile` already chains into `startPairingLoop` (`PrinterConnectionCoordinator.swift:193`), so the user lands directly in the fresh-scan UI.

## Pass B — Failure feedback polish

### B1. Name the printer in the headline

`MainView.swift:101–115`

When `pairingRecoveryMode == .reconnectFallback` and `reconnectRecoveryTargetDisplayName != nil`:
- Replace `"No printer connected"` with `L("couldnt_reach_printer", target)`.
- Drop the redundant `pairing_stage_connect_failed` subtitle (lines 105–115) — the headline now carries that signal.

New string `couldnt_reach_printer` ("Couldn't reach %@") in all 12 locale files.

### B2. Warning banner on reconnect failure

`macos/InstantLink/Core/PrinterConnectionCoordinator.swift:enterReconnectFallback` (line 567)

After the snapshot mutation, emit a sticky warning banner so the failure surfaces in the existing global banner system (the `BannerStrip` shipped in 043):

```swift
emitStatus(.show(PrinterConnectionStatusMessage(
    text: L("couldnt_reach_printer_banner", target),
    tone: .warning,
    autoDismiss: false
)))
```

`autoDismiss: false` is the same pattern already used for "Queue limit reached" (`ViewModel.swift:661`). The banner clears on the next `emitStatus(.dismiss)` — which `startPairingLoop` already fires at line 223 when the user retries — or via the BannerStrip dismiss button.

New string `couldnt_reach_printer_banner` ("Couldn't reach %@. Try again, switch, or forget.") in all 12 locales.

### B3. Bluetooth-recovery hint under the checklist

`MainView.swift:116–123`

Add a one-line `Label` after the 3-step checklist, visible only when `pairingRecoveryMode == .reconnectFallback`:

```swift
if viewModel.pairingRecoveryMode == .reconnectFallback {
    Label(L("bluetooth_hint_after_failed_reconnect"), systemImage: "info.circle")
        .font(.caption)
        .foregroundColor(.secondary)
}
```

New string `bluetooth_hint_after_failed_reconnect` ("If pairing keeps failing, check System Settings → Bluetooth") in all 12 locales.

## Pass C — Code cleanup

`macos/InstantLink/Core/PrinterConnectionCoordinator.swift`

### C1. Collapse dead conditional (lines 228–232)

Currently:
```swift
if disconnectCurrentPrinter || self.snapshot.isConnected {
    await self.ffi.disconnectPrinter()
} else {
    await self.ffi.disconnectPrinter()
}
```

The `disconnectCurrentPrinter` parameter is plumbed from `deleteProfile(line 193)` precisely so the FFI hop can be skipped when nothing is connected. Restore that intent:

```swift
if disconnectCurrentPrinter || self.snapshot.isConnected {
    await self.ffi.disconnectPrinter()
}
```

### C2. Single `currentReconnectTarget()` evaluation (lines 238–239)

Currently:
```swift
if let reconnectTarget = self.currentReconnectTarget() {
    let target = self.currentReconnectTarget() ?? reconnectTarget
    ...
}
```

Both calls read the same state but a concurrent mutation could make the second return a different value, which would then silently win. Bind once:

```swift
if let target = self.currentReconnectTarget() {
    ...
}
```

(Drop the `reconnectTarget` local — it was only used to feed the redundant call.)

## Strings (12 locales)

Add to all of `macos/Resources/{en,de,es,fr,it,ja,ko,pt-BR,zh-Hans,zh-Hant,ar,he}.lproj/Localizable.strings`:

| Key | English | zh-Hans |
|---|---|---|
| `couldnt_reach_printer` | `"Couldn't reach %@"` | `"无法连接 %@"` |
| `couldnt_reach_printer_banner` | `"Couldn't reach %@. Try again, switch, or forget."` | `"无法连接 %@。请重试、切换或忘记。"` |
| `bluetooth_hint_after_failed_reconnect` | `"If pairing keeps failing, check System Settings → Bluetooth"` | `"若反复失败，请检查系统设置 → 蓝牙"` |

For the other 10 locales, ship the English text as the value so the key exists and `L()` doesn't fall back to the key name. Translators will fill them in later — matches the established pattern in this repo.

## Verification

- App builds via `bash scripts/build-app.sh <version>` cleanly.
- Manually: with Pi off + Bridge off + printer off, click Reconnect → ~6 s spinner → "Couldn't reach …" headline appears, warning banner sticks at top, Bluetooth hint appears under the checklist, Forget Printer button appears below Reconnect/Switch. Forget → confirmation dialog → Delete → app drops into fresh-scan UI.
- Banner persists across re-clicks of Reconnect until pairing succeeds, the user dismisses it, or the user forgets the printer.

## Out of scope

- Reworking the picker sheet (F3 from 045).
- Exponential-backoff retry / `attemptConnection` timeout tuning (F9).
- New BannerStrip action variant (banner with inline Forget button) — keep the action affordances in the Main view buttons.
