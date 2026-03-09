# Plan 001: Full-Stack Scaffold

**Status:** Completed

Historical implementation plan from the initial scaffold. Current source-of-truth behavior lives in the reference and development docs, which reflect later additions such as Rust 2024, Mini Link 3 support, the expanded FFI surface, and the macOS overlay editor.

## Goal

Scaffold the entire InstantLink project from scratch: workspace, all crates, stub modules, full implementations, and macOS app. Verify compilation, clippy, formatting, and tests.

## Context

InstantLink is a Rust CLI and native macOS app for printing to Fujifilm Instax Link printers via BLE. The architecture mirrors [StatusLight](https://github.com/wu-hongjun/StatusLight), adapted from USB HID to BLE and from sync to async.

## Implementation Phases

### Phase 1: Scaffold (Completed)

Created workspace root, all Cargo.toml files, CLAUDE.md, .gitignore, and directory structure.

**Files created:**

- `Cargo.toml` — Workspace with 3 crates, workspace dependencies, release profile
- `CLAUDE.md` — Dev instructions, protocol reference, model specs
- `.gitignore` — Rust, macOS, IDE, references patterns

### Phase 2: Protocol + Commands (Completed)

Implemented the BLE packet protocol and all command opcodes.

**`protocol.rs`:**

- Packet header `[0x41 0x62]`, big-endian length, checksum
- `build_packet()` and `parse_packet()` with full validation
- `fragment()` for MTU-sized sub-packets (182 bytes)
- `PacketAssembler` for reassembling fragmented notifications
- 14 unit tests

**`commands.rs`:**

- 14 opcode constants (device info, battery, image transfer, LED, etc.)
- `Command` enum (12 variants) with `encode()` to protocol packets
- `Response` enum (10 variants) with `decode()` from parsed packets
- 14 unit tests including encode-decode roundtrips

### Phase 3: Image Processing (Completed)

**`image.rs`:**

- `FitMode` enum: Crop, Contain (white bars), Stretch
- `load_image()` from file path, `load_image_from_bytes()` from raw data
- `resize_image()` with model-aware dimensions using Lanczos3 filter
- `encode_jpeg()` with automatic quality reduction to fit the target printer's size limit
- `chunk_image_data()` using model-specific chunk sizes
- `prepare_image()` pipeline: load → resize → encode → chunk
- 10 unit tests

### Phase 4: Models + Transport + Device (Completed)

**`models.rs`:**

- `PrinterModel` enum with model specs (dimensions, chunk size, name, image-size limits)

**`transport.rs`:**

- `Transport` trait (async: send, receive, disconnect)
- BLE service/characteristic UUIDs
- `get_adapter()`, `scan()` using btleplug with service UUID filter
- `BleTransport` with notification channel and `PacketAssembler`

**`device.rs`:**

- `PrinterDevice` trait (async: status, battery, film, print, LED)
- `BlePrinterDevice` with model auto-detection via `IMAGE_SUPPORT_INFO`
- ACK-based print flow: `DOWNLOAD_START` → `DATA` chunks → `DOWNLOAD_END` → `PRINT_IMAGE`
- Progress callback support

### Phase 5: High-Level API + CLI (Completed)

**`printer.rs`:**

- `scan()`, `connect()`, `connect_any()`, `print_file()`, `get_status()`

**CLI (`main.rs` + `output.rs`):**

- Commands: `scan`, `info`, `print`, `led set/off`, `status`
- Global `--device` flag and JSON output where supported by the CLI
- Progress bars via indicatif
- JSON output for all commands

### Phase 6: FFI + macOS App (Completed)

**FFI (`lib.rs`):**

- Global tokio runtime via `OnceLock`
- `Mutex`-protected device handle
- Functions: `init`, `connect`, `disconnect`, `battery`, `film_remaining`, `print`, `set_led`, `led_off`, `is_connected`
- `catch_unwind` on all FFI boundaries
- cbindgen auto-generates `instantlink.h`

**macOS App:**

- `InstantLinkCLI.swift` — Process wrapper with 15s watchdog, scan/info/print/LED/status
- `InstantLinkApp.swift` — SwiftUI with menu bar extra, full window, drag-and-drop print zone
- `build-app.sh` — Builds CLI + copies into app bundle

## Verification

| Check | Result |
|-------|--------|
| `cargo build --workspace` | Pass |
| `cargo clippy --workspace -- -D warnings` | Pass (0 warnings) |
| `cargo fmt --all` | Pass |
| `cargo test --workspace` | Passed at scaffold completion; current totals have since grown |

## Key Decisions

1. **Async-first**: btleplug requires tokio, so core is fully async
2. **No daemon**: One-shot printing doesn't need a persistent service
3. **Process wrapper over FFI**: the initial plan followed the StatusLight process-wrapper pattern; the shipped macOS app now uses the FFI dylib directly for printer control
4. **Model auto-detection**: Query `IMAGE_SUPPORT_INFO` after connect, match dimensions
5. **ACK-per-chunk**: Wait for printer ACK after each data chunk (reliable transfer)
