# FFI Reference

`instantlink-ffi` exposes the Rust core through a C ABI for Swift, C, and other native callers.

## Build

```bash
cargo build --release -p instantlink-ffi
```

Artifacts:

- `target/release/libinstantlink_ffi.dylib`
- `target/release/libinstantlink_ffi.a`

By default, cbindgen writes the generated header into Cargo's `OUT_DIR`. To refresh the checked-in header at `crates/instantlink-ffi/include/instantlink.h`, build with:

```bash
INSTANTLINK_UPDATE_HEADER=1 cargo build --release -p instantlink-ffi
```

To verify that the checked-in header matches the generated ABI without leaving drift behind, run:

```bash
bash scripts/check-ffi-header.sh --release
```

Release CI runs this drift check before packaging the FFI zip, so `InstantLink-FFI-*.zip` only ships with a header that matches the generated bindings.

## Status Codes

All exported functions return `i32` status codes:

| Code | Meaning |
|------|---------|
| `0` | Success |
| `-1` | Printer not found or no device connected |
| `-2` | Multiple printers found |
| `-3` | BLE/protocol/internal error or panic caught |
| `-4` | Timeout |
| `-5` | Invalid argument |
| `-6` | Image processing error |
| `-7` | Print rejected or unexpected device response |
| `-8` | No film remaining |
| `-9` | Battery too low |
| `-10` | Printer cover is open |
| `-11` | Printer is busy |

## Connection Progress Callbacks

Specific reconnect/pairing flows can use `instantlink_connect_named_with_progress(...)` or `instantlink_connect_named_with_progress_ctx(...)` to receive connection-stage events.

### Base Callback (without context)

```c
typedef void (*instantlink_connect_stage_cb)(int32_t stage, const char *detail);
```

### Context Callback (macOS app preference)

```c
typedef void (*instantlink_connect_stage_cb_ctx)(int32_t stage, const char *detail, void *context);
```

The `_ctx` variant allows passing an opaque `context` pointer that is returned unchanged to each callback invocation, enabling stateful per-call tracking without global state.

| Stage | Code | Meaning |
|------|------|---------|
| `scan_started` | `0` | BLE scan started |
| `scan_finished` | `1` | BLE scan finished |
| `device_matched` | `2` | Matching printer advertisement found |
| `ble_connecting` | `3` | CoreBluetooth connection starting |
| `service_discovery` | `4` | GATT service discovery |
| `characteristic_lookup` | `5` | Write/notify characteristic resolution |
| `notification_subscribe` | `6` | Notification subscription |
| `model_detecting` | `7` | Printer model detection |
| `status_fetching` | `8` | Initial status fetch |
| `connected` | `9` | Connection is ready for use |
| `failed` | `10` | Connection failed |

`detail` is optional stage-specific context and is only valid during the callback invocation. Like the print progress callback, the connect-stage callback is invoked from the runtime thread, so UI callers must marshal updates back to the main thread.

## Exported Functions

### Lifecycle

```c
void instantlink_init(void);
int32_t instantlink_connect(void);
int32_t instantlink_connect_named(const char *name, int32_t duration_secs);
int32_t instantlink_connect_named_with_progress(const char *name,
                                                int32_t duration_secs,
                                                instantlink_connect_stage_cb progress_cb);
int32_t instantlink_connect_named_with_progress_ctx(const char *name,
                                                    int32_t duration_secs,
                                                    instantlink_connect_stage_cb_ctx progress_cb,
                                                    void *context);
int32_t instantlink_disconnect(void);
int32_t instantlink_is_connected(void);
int32_t instantlink_shutdown(void);
int32_t instantlink_reset(void);
```

- `instantlink_is_connected` returns `1` for a cached session not known closed, `0` for no session or a terminally closed session, or a negative error code. It is a cheap read-only check: it does not poll hardware or guarantee that a physical link is live.
- `instantlink_connect_named_with_progress` is the base entry point for UI-driven reconnect flows; exposes real connection stages
- `instantlink_connect_named_with_progress_ctx` is the preferred variant (used by macOS app) because it accepts an opaque `context` pointer, allowing per-call state without global side effects. The context is passed unchanged to each callback invocation.
  - **Context Pointer Contract**: The `context` pointer is cast to `usize` internally and back; the FFI does not dereference it. The caller is responsible for ensuring the pointer remains valid for the entire duration of the connect operation and properly life-managing the backing object.
  - **Callback Invocation**: The connect-stage callback is invoked from the tokio runtime thread. Native (UI) callers must marshal updates back to the main thread (e.g., via Grand Central Dispatch on macOS).
  - **Thread Safety**: Multiple concurrent calls with different context pointers are safe; the FFI serializes internal device state but allows independent progress tracking per call.
- `instantlink_shutdown` powers off the connected printer
- `instantlink_reset` resets the connected printer

### Scanning

```c
int32_t instantlink_scan(int32_t duration_secs, char *out_json, int32_t out_len);
```

Writes a JSON array of printer names into `out_json` and returns the number of bytes written.

### Status Queries

```c
int32_t instantlink_battery(void);
int32_t instantlink_film_remaining(void);
int32_t instantlink_film_and_charging(int32_t *out_film, int32_t *out_charging);
int32_t instantlink_print_count(void);
int32_t instantlink_status(int32_t *out_battery, int32_t *out_film,
                           int32_t *out_charging, int32_t *out_print_count);
int32_t instantlink_device_name(char *out, int32_t out_len);
int32_t instantlink_device_model(char *out, int32_t out_len);
```

### Printing

```c
int32_t instantlink_print(const char *path, uint8_t quality,
                          uint8_t fit_mode, uint8_t print_option);
int32_t instantlink_print_with_progress(const char *path, uint8_t quality,
                                        uint8_t fit_mode, uint8_t print_option,
                                        void (*progress_cb)(uint32_t sent, uint32_t total));
int32_t instantlink_print_with_progress_ctx(const char *path, uint8_t quality,
                                            uint8_t fit_mode, uint8_t print_option,
                                            instantlink_print_progress_cb_ctx progress_cb,
                                            void *context);
```

The print-progress callback type:

```c
typedef void (*instantlink_print_progress_cb_ctx)(uint32_t sent, uint32_t total, void *context);
```

#### Parameters

- `fit_mode`: `0 = crop`, `1 = contain`, `2 = stretch`
- `print_option`: `0 = Rich`, `1 = Natural`
- `progress_cb` is optional and receives acknowledged chunk progress

#### Progress Context Variant

`instantlink_print_with_progress_ctx` is the preferred variant (used by macOS app) for the same reasons as its connect counterpart:

- **Context Pointer Contract**: The `context` pointer is cast to `usize` internally; the FFI does not dereference it. Ensure the pointer remains valid for the entire print operation.
- **Callback Invocation**: Progress callbacks are invoked from the tokio runtime thread after each chunk is acknowledged. UI callers must synchronize state updates (e.g., via Grand Central Dispatch).
- **Thread Safety**: The context pointer is thread-safe by design since it is passed opaque and unchanged to each callback.

### Prepared JPEG Printing

Callers that already perform model-specific image preparation can send their final JPEG
without another resize, flip or JPEG encode:

```c
int32_t instantlink_print_prepared_jpeg(const uint8_t *data, uint32_t data_len,
                                        uint8_t expected_model,
                                        uint8_t transport_flip_applied,
                                        uint8_t print_option);
int32_t instantlink_print_prepared_jpeg_with_progress(const uint8_t *data,
                                                      uint32_t data_len,
                                                      uint8_t expected_model,
                                                      uint8_t transport_flip_applied,
                                                      uint8_t print_option,
                                                      void (*progress_cb)(uint32_t, uint32_t));
int32_t instantlink_print_prepared_jpeg_with_progress_ctx(const uint8_t *data,
                                                          uint32_t data_len,
                                                          uint8_t expected_model,
                                                          uint8_t transport_flip_applied,
                                                          uint8_t print_option,
                                                          instantlink_print_progress_cb_ctx progress_cb,
                                                          void *context);
```

| Model | `expected_model` | Dimensions | Maximum bytes | `transport_flip_applied` |
| --- | --- | --- | --- | --- |
| Mini | 0 | 600×800 | 105,000 | 0 |
| Mini Link 3 | 1 | 600×800 | 55,000 | 1 |
| Square | 2 | 800×800 | 105,000 | 0 |
| Wide | 3 | 1260×840 | 225,000 | 0 |

The exact detected model must match, including Mini versus Mini Link 3. JPEG data must be a
complete 8-bit, three-component baseline JPEG with exact dimensions, within the model's byte
budget and without trailing data. Progressive, grayscale, CMYK, arithmetic/lossless JPEG and
recognized non-neutral EXIF orientation are rejected. Raw pixel orientation is authoritative.
Mini Link 3's vertical transport flip must be applied **before encoding**; the native path
validates the declaration and transmits those bytes unchanged. It cannot infer orientation
from arbitrary pixel content, so the caller must uphold that declaration.

The core performs a bounded full decode with warnings treated as errors to detect incomplete
entropy scans; it discards validation pixels and performs no new encode. Validation failure
returns `-6` before any Printer write. Null/empty input, unknown model or flip values outside
0/1 return `-5`; no connected device returns `-1`. No legacy retry occurs after a failed send.

`data` must remain readable and unchanged for the entire synchronous call. Callbacks/context
must stay alive until return; callbacks occur after acknowledged chunks and never afterwards.
The global device mutex is released before callbacks, while the per-Printer operation lock
serializes the transaction. Callbacks must not synchronously start another serialized Printer
operation; identity getters are safe. Marshal UI work to the UI thread. All three exports catch
Rust panics; the existing file-based functions remain available.

The Bridge detects this optional export in its FFI wrapper. Compatible native builds use an
in-memory byte buffer and correctly oriented prepared JPEG; older builds use the legacy
unflipped preparation/file path. Physical and virtual LCD previews reverse the transport flip
only when rendering. No management or sync API field is added.

### LED Control

```c
int32_t instantlink_set_led(uint8_t r, uint8_t g, uint8_t b, uint8_t pattern);
int32_t instantlink_led_off(void);
```

- `pattern`: `0 = solid`, `1 = blink`, `2 = breathe`

### Keepalive

```c
int32_t instantlink_keepalive(void);
int32_t instantlink_set_keepalive_interval(int32_t seconds);
```

- Missing native replies trigger a bounded link-state check after one second. Confirmed disconnection closes the old session; inconclusive checks retain the original command deadline. Normal acknowledgements and idle sessions add no checks. Commands are never replayed.
- `instantlink_keepalive` sends one status/keepalive request to the connected printer (`0` on success)
- `instantlink_set_keepalive_interval` configures the background keepalive: `0` disables it, positive values are seconds; a negative value returns `-5`

## Swift Usage

The macOS app loads the dylib via `dlopen` and resolves the exported symbols in `InstantLinkFFI.swift` (located at `macos/InstantLink/InstantLinkFFI.swift`). This file demonstrates:

- Bridging the C FFI functions into Swift async/await methods
- Using `instantlink_connect_named_with_progress_ctx` with a boxed Swift closure to deliver connection-stage updates
- Using `instantlink_print_with_progress_ctx` with a boxed Swift closure to deliver print-progress updates
- Dispatching FFI calls onto a dedicated serial queue to prevent race conditions

Example pattern for context-boxed callbacks:

```swift
let boxPtr = Unmanaged.passRetained(CallbackBox(closure: { /* ... */ }))

let callback: @convention(c) (Int32, UnsafePointer<CChar>?, UnsafeMutableRawPointer?) -> Void = {
    stage, detail, context in
    guard let context else { return }
    let box = Unmanaged<CallbackBox>.fromOpaque(context).takeUnretainedValue()
    box.closure(stage)
}

// Call FFI with boxPtr.toOpaque() as context
boxPtr.release()  // when done
```

## Thread Safety

The FFI layer owns:

- a global `tokio` runtime via `OnceLock<Runtime>`
- a `Mutex`-protected connected device handle
- `catch_unwind` guards on all exported functions

The macOS wrapper serializes FFI calls on a dedicated serial dispatch queue so reconnect, status, and print operations do not race each other.

**Callback Threads**: Progress callbacks (connect-stage and print-progress) are invoked from the tokio runtime thread, not the main thread. Native callers must marshal updates back to the main thread (e.g., via `DispatchQueue.main.async` on macOS).

**Context Pointer Safety**: The `_ctx` variants pass the context pointer opaque and unchanged; the FFI does not dereference or copy it. Callers are responsible for lifetime and thread safety of the backing object during the operation.
