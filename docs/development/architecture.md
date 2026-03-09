# Architecture

InstantLink follows a layered architecture mirroring [StatusLight](https://github.com/wu-hongjun/StatusLight).

## Crate Dependency Graph

```
instantlink-cli ──→ instantlink-core
instantlink-ffi ──→ instantlink-core
macOS app ─────→ instantlink-ffi (via dlopen, bundled dylib)
```

## instantlink-core

The core library handles all BLE communication and image processing. It is fully async (tokio + btleplug).

### Module Layers

```
printer.rs     ← High-level API (scan, connect, print_file)
    ↓
device.rs      ← PrinterDevice trait + BlePrinterDevice (ACK flow)
    ↓
transport.rs   ← BLE GATT transport (btleplug)
    ↓
commands.rs    ← Command/Response enums, encode/decode
    ↓
protocol.rs    ← Packet build/parse, checksum, fragmentation
    ↓
models.rs      ← PrinterModel enum + specs
error.rs       ← PrinterError + Result alias
image.rs       ← Load, resize, JPEG encode, chunk
```

### Key Design Decisions

**Async throughout**: btleplug requires tokio, so the entire core is async. The `PrinterDevice` trait uses `async_trait`.

**Model auto-detection**: After connecting, we query `IMAGE_SUPPORT_INFO` and match the returned width/height to a `PrinterModel`. This determines image dimensions and chunk sizes.

**ACK-based flow**: Each data chunk requires an ACK from the printer before sending the next. This is handled in `BlePrinterDevice::send_image_data`.

**Automatic quality reduction**: If the JPEG exceeds 105KB, a binary search finds the highest quality that fits within the limit.

**Transport trait**: `transport::Transport` is a trait, enabling mock implementations for testing without hardware. A `MockTransport` (in `device.rs` `#[cfg(test)]` block) uses a FIFO response queue and sent-bytes recording to test the full device layer — model detection, status queries, ACK-based print flow, LED commands, and error paths.

## instantlink-cli

Thin CLI layer using clap for argument parsing and indicatif for progress bars. All printer operations delegate to `instantlink_core::printer`.

Supports `--json` output on all commands for machine consumption.

## instantlink-ffi

C FFI bindings using cbindgen. Manages a global tokio runtime (`OnceLock<Runtime>`) and a `Mutex`-protected device handle. All functions use `catch_unwind` to prevent Rust panics from crossing the FFI boundary.

## macOS App

Native SwiftUI app with menu bar extra and full window. Single-file architecture (`InstantLinkApp.swift`) containing all views and the ViewModel. Communicates with printers via FFI — `InstantLinkFFI.swift` uses `dlopen`/`dlsym` to load the bundled `libinstantlink_ffi.dylib` and resolves all 17 symbols at runtime.

### Key Features

- **Image editor**: Crop, contain, stretch fit modes; rotation; date stamps with multiple styles
- **Camera capture**: Built-in camera with self-timer (off/2s/10s) and capture flash
- **Film orientation**: Portrait/landscape toggle that inverts the aspect ratio for preview and applies 90° rotation at print time
- **Film border preview**: `FilmFrameView` renders the physical Instax film card shape (white card with thick bottom border) around image previews
- **Printer profiles**: Multi-printer management with custom names, colors, and saved BLE identifiers
- **Auto-update**: Checks GitHub releases and downloads/installs updates in-app
- **Localization**: 12 languages via `.lproj/Localizable.strings` bundles

## No Daemon

Unlike StatusLight, InstantLink has no daemon crate. Instax printing is inherently one-shot: connect, transfer image, print, disconnect. There's no need for a persistent background service.
