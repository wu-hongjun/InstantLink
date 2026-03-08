# Plan 004: App Bundle and Release Pipeline

**Status:** Completed

## Goal

Set up a proper macOS app bundle build using `swiftc` (no Xcode project), matching the StatusLight pattern. Update the release workflow to produce a `.dmg`.

## Changes

### Build Script (`scripts/build-app.sh`)

Rewrote to match StatusLight's approach:

1. Takes a `<version>` argument (e.g., `0.1.0` or `v0.1.0`)
2. Expects pre-built release binary at `target/release/openinstax`
3. Creates `OpenInstax.app/Contents/` structure:
   - `MacOS/openinstax-cli` — CLI binary (renamed to avoid case collision with launcher)
   - `MacOS/OpenInstax` — SwiftUI launcher compiled with `swiftc`
   - `Info.plist` — Generated from template with version substitution
   - `PkgInfo` — Standard `APPL????`
4. Ad-hoc codesigns the bundle
5. Optionally creates DMG using `create-dmg`

### Info.plist.template

- Bundle ID: `com.openinstax.app`
- `LSUIElement: true` (menu bar app, no dock icon by default)
- `NSBluetoothAlwaysUsageDescription` for BLE permission
- Minimum macOS 13.0 (Ventura)
- Version substituted at build time

### CLI Binary Naming

The CLI binary is renamed `openinstax-cli` inside the bundle to avoid a case-insensitive filesystem collision with the SwiftUI launcher binary (`OpenInstax`). `OpenInstaxCLI.swift` updated to look for `openinstax-cli`.

### Release Workflow

Updated to:
1. Install `create-dmg` via Homebrew
2. Build Rust workspace
3. Run `build-app.sh` to create `.app` and `.dmg`
4. Package CLI and FFI zips
5. Upload DMG + zips to GitHub Release

### README.md

Updated with CI badge, proper installation instructions, usage examples, project structure, and documentation link.

## Key Decisions

1. **No Xcode project**: Use `swiftc` directly, matching StatusLight — simpler, no IDE dependency
2. **CLI rename in bundle**: `openinstax` → `openinstax-cli` avoids APFS case collision
3. **BLE permission**: `NSBluetoothAlwaysUsageDescription` in Info.plist is required for CoreBluetooth
