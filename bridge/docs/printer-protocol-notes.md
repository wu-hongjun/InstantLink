# Printer Protocol Notes

The working full implementation is available in the parent InstantLink workspace. As of ADR-009,
the v1 runtime uses InstantLink's Rust FFI by default instead of the Python/Bleak transport:

```text
../crates/instantlink-ffi
src/instantlink_bridge/ble/instantlink.py
```

Primary implementation reference:

- `../crates/instantlink-core/src/protocol.rs`
- `../crates/instantlink-core/src/printer.rs`
- `../crates/instantlink-core/src/transport.rs`
- `../crates/instantlink-core/src/commands.rs`
- `../crates/instantlink-core/src/models.rs`
- `../crates/instantlink-core/src/image.rs`

Additional references:

- `javl/InstaxBLE`: canonical public Python reference.
- `dgwilson/ESP32-InstantBridge`: ESP32 printer simulator for development without burning film.

## Instax Link Facts

- Printer family: Fujifilm Instax Link BLE.
- Target models: Mini Link, Mini Link 3, Square Link, and Wide Link.
- Expected input image sizes: Mini/Mini Link 3 600x800, Square 800x800, Wide 1260x840.
- BLE generation: BLE 4.2 class device.
- Advertising name pattern: `INSTAX-XXXXXXXX`.
- Protocol families differ across Mini, Square, and Wide Link printers.
- No public reference in this repo documents a supported command to disable printer sleep or hold
  a wake lock. Use benign BLE activity for keepalive.

## Model Detection

Do not hard-code a printer model in normal operation. The bridge should query Image Support Info
after BLE notification subscription and infer the film/output format from the reported dimensions:

| Reported dimensions | Format/model family |
| --- | --- |
| `600x800` | Mini / Mini Link family |
| `800x800` | Square Link |
| `1260x840` | Wide Link |

If the Device Information Service model number contains `FI033`, treat the `600x800` printer as
Mini Link 3 for protocol timing/flip behavior. Otherwise, report it as Mini format.

## v1 Scope

- Support one selected Instax Link printer at a time.
- Do not require BlueZ bonding. Selection persists the normalized printer name in
  `/var/lib/InstantLinkBridge/printer.json`.
- Use InstantLink's Rust backend for scan, connect, model detection, status, and BLE transfer.
- Keep the Python preprocessing path for JPEG/HIF/ARW ingest, preview edits, and model-sized
  temporary JPEGs. Pass those files to InstantLink with fit mode `stretch` so InstantLink performs
  only its model-specific transport transforms.
- Keep the BLE connection open and poll status every 10 s by default while the selected printer is
  online. This keeps film/battery current on the LCD and is the v1 printer-awake mechanism.

## Implementation Status

The default runtime wrapper is `src/instantlink_bridge/ble/instantlink.py`. It loads
`/opt/InstantLinkBridge/lib/libinstantlink_ffi.so`, calls the InstantLink FFI through `ctypes`, and
keeps the previous Python/Bleak transport available only when
`INSTANTLINK_BRIDGE_PRINTER_BACKEND=bleak` is set.
