# Repository Guidelines

## Product Vocabulary

Use the project names consistently in code, docs, and user-facing copy:

- **InstantLink** is the umbrella project and repository.
- **App** means the native macOS app in `macos/`; do not use it for the Bridge or iOS app.
- **Bridge** means the Raspberry Pi appliance in `bridge/`.
- **iOS app** means the iPhone companion in `ios/`.
- **Printer** means a Fujifilm Instax Link device.

The App talks directly to a Printer over the Rust FFI and manages a Bridge over HTTP. The Bridge receives camera uploads over FTP, can print through the same Rust FFI, and can expose photos and its virtual LCD to the iOS app through the sync API.

## Project Structure and Ownership

- `crates/instantlink-core/src/` is the authoritative printer implementation: async BLE transport, packet/command handling, model detection, printer/device APIs, and image preparation.
- `crates/instantlink-cli/src/` is the thin `clap` frontend around the core crate.
- `crates/instantlink-ffi/` exposes the core through a C ABI. Its committed public header is `crates/instantlink-ffi/include/instantlink.h`.
- `macos/InstantLink/` is a SwiftUI app compiled directly with `swiftc`, not an Xcode project. `App/` contains lifecycle code, `Core/` contains shared state and printer/Bridge coordinators, `Features/` contains Bridge, Camera, Editor, Main, and Settings UI, and `Support/` contains reusable UI. Tests use the repo-native harness in `macos/Tests/`; assets and 12 localizations live in `macos/Resources/`.
- `bridge/src/instantlink_bridge/` is the typed Python appliance runtime. `app.py` orchestrates FTP, printing, sync, UI, power, and networking; `ble/instantlink.py` wraps the default Rust FFI backend; `camera/`, `imaging/`, `sync/`, `ui/`, `manager/`, `net/`, and `power/` own their respective boundaries. Operational files live in `bridge/config/`, `systemd/`, `udev/`, and `scripts/`, with tests in `bridge/tests/`.
- `ios/` is the SwiftUI iPhone companion. `ios/project.yml` is the XcodeGen source of truth; `ios/InstantLink-iOS.xcodeproj/` is generated and ignored. Models, services, view models, views, resources, and XCTest coverage are split under `ios/InstantLink/` and `ios/InstantLinkTests/`.
- `docs/` is the MkDocs source, including numbered design/implementation records in `docs/plans/`. `brand/` contains canonical SVGs and palette guidance. Root `scripts/` contains shared build and validation automation.

Do not edit generated output such as `target/`, `site/`, caches, virtual environments, DMGs, or the generated iOS Xcode project. Do not revive the old standalone InstantBridge implementation or `/opt/InstantBridge` paths; the maintained Bridge lives in this repository and installs under `/opt/InstantLinkBridge`.

## Architecture Boundaries

- Keep Instax protocol, model, transport, and reusable image rules in `instantlink-core`; do not reimplement them in the CLI or Swift. The Bridge's Python/Bleak printer path is diagnostic fallback only; the Rust FFI is the default backend.
- Keep macOS FFI loading in `InstantLinkFFI.swift` and Bridge FFI loading in `bridge/src/instantlink_bridge/ble/instantlink.py`, away from UI code.
- FFI entry points must remain panic-safe and concurrency/callback-safe. When exports change, regenerate the committed header with `INSTANTLINK_UPDATE_HEADER=1 cargo build -p instantlink-ffi --locked`, then run the header drift check.
- The Bridge sync server and iOS client are one contract. Changes under `bridge/src/instantlink_bridge/sync/` normally require matching review of `ios/InstantLink/Models/`, `ios/InstantLink/Services/`, and `docs/reference/sync-api.md`.
- Bridge management configuration spans the Python schema/API and the macOS Bridge models/schema/UI. Update both sides together when a field or payload changes.
- The physical and virtual Bridge LCD share one state machine and render path. Remote input must inject the same abstract UI actions as GPIO input rather than creating a second UI implementation.

## Build, Test, and Development Commands

Run Rust and shared macOS checks from the repository root:

```bash
cargo build --workspace --locked
cargo fmt --all -- --check
cargo clippy --workspace --locked -- -D warnings
cargo test --workspace --locked
bash scripts/check-ffi-header.sh
bash scripts/test-macos.sh
python3 scripts/check-localizations.py
```

Build the macOS app with `bash scripts/build-app.sh <semver>`. It produces `target/release/InstantLink.app` and creates a DMG when `create-dmg` is installed. The app baseline is arm64 macOS 15.0. Keep the three Rust crate versions in sync with the App release version; the Bridge version in `bridge/pyproject.toml` and iOS version in `ios/project.yml` are independent.

Install the CLI locally with `cargo install --path crates/instantlink-cli`. Build a Bridge firmware archive with `bash bridge/scripts/build-firmware-bundle.sh <version-or-tag>`; this cross-builds Linux arm64 CLI/FFI artifacts and stages release output under `target/bridge-firmware/`. Read `docs/development/bridge-firmware-release.md` before signing or publishing firmware.

Set up and validate the Bridge with Python 3.11-3.13:

```bash
python3 -m venv bridge/.venv
bridge/.venv/bin/pip install -c bridge/requirements/constraints.txt -e 'bridge[dev]'
cd bridge
python -m ruff format --check src tests
python -m ruff check src tests
python -m mypy src
python -m pytest -q
```

Generate and test the iOS 17 / Swift 5.9 project with XcodeGen. Replace the simulator name with one reported by `xcrun simctl list devices available` when necessary:

```bash
cd ios
xcodegen generate
xcodebuild test -project InstantLink-iOS.xcodeproj -scheme InstantLink-iOS \
  -destination 'platform=iOS Simulator,name=iPhone 17' CODE_SIGNING_ALLOWED=NO
```

Preview or strictly validate docs with `mkdocs serve` and `mkdocs build --strict` after installing `mkdocs-material`. Enable the tracked path-scoped pre-commit checks with `git config core.hooksPath scripts/git-hooks`.

## Coding Style

Rust uses edition 2024 and default `rustfmt`: `snake_case` for functions/modules, `PascalCase` for types, and `SCREAMING_SNAKE_CASE` for constants. Use `PrinterError`/`thiserror` for reusable core failures and `anyhow::Context` for CLI-facing context. Preserve async cancellation, command serialization, and mockable transport boundaries.

Bridge Python is formatted and linted with Ruff at 100 columns and checked with strict mypy. Type every function and method, prefer `pathlib.Path`, use `asyncio` primitives instead of threads, and keep camera, imaging, BLE, UI, power, network, manager, and watchdog I/O boundaries separable. Preserve structured event logging and avoid per-poll warning spam.

For Swift, follow the existing SwiftUI organization and concurrency annotations. Keep side effects in services/coordinators or view models rather than views. macOS user-facing strings must use `L()`/localization keys and be added across all locale bundles. Treat `project.yml`, not generated Xcode files, as the iOS build configuration.

Shell scripts use `set -euo pipefail` when appropriate and must pass `bash -n`. Keep deployment operations explicit and configurable through the existing `INSTANTLINK_BRIDGE_*` environment variables.

## Testing and Hardware Verification

- Add Rust unit tests beside the implementation under `#[cfg(test)]`; use mock transports and paused Tokio time where possible so tests require no Printer.
- Add Bridge pytest coverage under `bridge/tests/` and mock LCD, GPIO, BlueZ, FTP, network, filesystem, and systemd boundaries. Hardware should not be required for the local suite.
- Add macOS logic tests under `macos/Tests/`. If a new production file is needed by that harness, also add it to `scripts/test-macos.sh`.
- Add iOS XCTest coverage under `ios/InstantLinkTests/`; network tests should use `URLProtocol` stubs and run in the simulator. The root pre-commit hook and release CI do not currently run the iOS suite, so run it explicitly for every `ios/` change.
- For BLE, printing, camera FTP, hotspot/Bonjour, GPIO/LCD, firmware update, Photos, or physical-device changes, record a manual smoke test and the hardware/OS used. Useful Printer checks are `cargo run -p instantlink-cli -- scan`, `status`, and `print <image>`.
- Test the smallest affected surface while iterating, then run every path-scoped check relevant to the final diff. CI is primarily a release-tag gate, so local validation is the day-to-day quality gate.

## Documentation, Commits, and Releases

Update live reference docs alongside behavior and public contract changes. Put substantial planned work in the next numbered file under `docs/plans/`; do not rewrite historical plans to pretend later decisions were original. For Bridge hardware/deployment work, also update `bridge/docs/current-context.md` when the verified device state changes.

Use focused Conventional Commit-style subjects matching current history: `feat:`, `fix:`, `polish:`, `docs:`, `refactor:`, `test:`, or `chore:`, with useful scopes such as `feat(bridge):` or `fix(ios):`. Pull requests should name the affected surfaces, describe user-visible or contract changes, list exact validation, and include screenshots for UI changes. Hardware work must name the Printer/Bridge/camera/iPhone model, relevant OS versions, and whether it was verified on real hardware.
