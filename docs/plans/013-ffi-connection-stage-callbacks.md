# Plan 013: FFI Connection Stage Callbacks

**Status:** In Progress (local implementation in progress; not committed yet)

## Objective

Expose truthful printer-connection progress from Rust to the macOS app so pairing UX can show real intermediate stages instead of only `Scanning...` and `Connecting to %@...`.

This is an API design and plumbing plan, not a backward-compatibility exercise. The goal is a cleaner FFI contract and a clearer app state model.

## Current Problem

- The macOS app only gets `Bool` from `InstantLinkFFI.connect(device:duration:)`.
- Real work happens inside Rust:
  - BLE scan result matching
  - peripheral connect
  - service discovery
  - characteristic lookup
  - notification subscribe
  - model detection
  - initial status fetch
- The UI cannot distinguish “waiting for Bluetooth connect” from “reading printer info,” so progress copy is vague and static.

## Design Principles

- Only surface stages we actually know.
- Keep the C ABI simple and stable: integer stage codes plus optional text payload.
- Reuse the same callback model for future CLI/app diagnostics if useful.
- Do not fake percent-complete for connection.

## Proposed FFI Surface

### Rust / C ABI

Add a new entry point alongside the existing `instantlink_connect_named`:

```c
typedef void (*instantlink_connect_stage_cb)(int32_t stage, const char *detail);

int32_t instantlink_connect_named_with_progress(
    const char *name,
    int32_t duration_secs,
    instantlink_connect_stage_cb progress_cb
);
```

Stage codes:

- `0` `scan_started`
- `1` `scan_finished`
- `2` `device_matched`
- `3` `ble_connecting`
- `4` `services_discovering`
- `5` `characteristics_resolving`
- `6` `notifications_subscribing`
- `7` `model_detecting`
- `9` `connected`
- `10` `failed`

`detail` should be optional and short, for example printer name or detected model.

`status_fetching` is intentionally synthesized in the macOS coordinator after FFI connect succeeds and before the first status query completes. It is not emitted directly by the Rust connect callback path.

## Rust Implementation

### `crates/instantlink-core`

- Add an internal progress callback type for `printer::connect(...)`.
- Thread it through:
  - `printer.rs`
  - `transport.rs`
  - `device.rs`
- Emit stage events exactly where the work occurs:
  - before scan
  - after match resolution
  - before/after BLE connect
  - before/after service discovery
  - before characteristic lookup
  - before subscribe
  - before model detection
  - before initial status query
  - on final success

### `crates/instantlink-ffi`

- Add `instantlink_connect_named_with_progress`.
- Keep existing `instantlink_connect_named` as a thin wrapper for callers that do not care about stages.
- Map Rust callback events to C callback invocations without allocating large strings.

## macOS Integration

### `macos/InstantLink/InstantLinkFFI.swift`

- Add a Swift enum `ConnectionStage`.
- Add a `connect(device:duration:progress:)` overload that forwards stage callbacks from C.
- Preserve the current simple overload as a convenience wrapper if still useful.

### `macos/InstantLink/Core/PrinterConnectionCoordinator.swift`

- Replace the current single `pairingStatus = connecting_to` update with stage-driven status updates.
- Add a small stage-to-copy mapper for user-visible text.
- Keep `pairingPhase` coarse (`scanning` / `connecting`) but store the richer current connection stage separately.

## UX Mapping

Recommended copy:

- `Scanning for printers...`
- `Found %@`
- `Opening Bluetooth connection...`
- `Setting up printer services...`
- `Reading printer information...`
- `Connected`

Rules:

- Show stage text, not percentages.
- Keep the current cancel affordance.
- Continue hiding “tips” once a specific printer is already being connected.
- If connection fails, preserve the last stage so the error is easier to interpret.

## Testing

- Unit-test stage emission order in Rust with mock transport.
- Verify connect success still works with no callback.
- Verify callback path does not leak or crash when callback is null.
- Build and smoke-test macOS pairing flow with:
  - saved printer
  - first-time printer
  - Bluetooth prompt shown
  - connect failure / retry

## Implementation Order

1. Add stage enum and callback plumbing in `instantlink-core`.
2. Add FFI entry point and header export in `instantlink-ffi`.
3. Add Swift wrapper and coordinator integration.
4. Update pairing UI copy in macOS.
5. Run Rust tests, app build, and manual pairing smoke tests.

## Exit Criteria

- The macOS app shows truthful connection stages during pairing.
- The old vague `Connecting to %@...` state is replaced by stage-aware status.
- Existing connect callers still work.
- No pairing regressions in saved-printer, switch-printer, or retry flows.
