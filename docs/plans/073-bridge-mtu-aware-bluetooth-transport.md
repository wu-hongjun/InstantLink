# MTU-aware Bridge Bluetooth transport

## Scope and decision

Implement negotiated fragments in authoritative Rust core, preserve prepared JPEG bytes and model
orientation, and verify Printer reconnects. Three subagents implemented, wrote independent fault
and packet tests, and performed adversarial review. No public FFI ABI, Python configuration, sync
contract, App UI, image processing, protocol pacing or SD cache change.

Linux reads the exact connected BlueZ write characteristic MTU once per connection with a bounded
one-second query. Production uses `min(MTU - 3, 236)`; absent or ambiguous metadata and other
platforms retain 182 bytes. Known small MTUs clamp either policy. Diagnostic comparison permits
244. All packet/ACK operations remain serialized; uncertain delivery is never replayed. Actual
large-write failures downgrade that device on a fresh connection and require link reset. A small
status failure requires reset without a false size downgrade. The process cache is bounded at 128.

## Physical paired print

Hardware: Pi Zero 2 W / ST7789 240×240 / X306 2300 mAh; Debian 13.2, Linux
6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82, Bridge 0.1.17. Instax Square
INSTAX-52006924. User-selected DSC02825.jpeg, saved Vivid saturation 1.5 / neutral Correction,
Auto fit. Real production FTP/UI/native printing; two sheets, no replay. Same-Pi hotspot-address
FTP excludes camera Wi-Fi airtime. Completion means Bridge/Printer command completion, not timed
mechanical ejection or film development.

| Metric | Stable 182 | Candidate 244 |
|---|---:|---:|
| FTP start → Bridge completion | 27.934 s | 28.375 s |
| Native handoff → completion | 23.224 s | 24.089 s |
| Download start → End ACK | 21.837 s | 22.724 s |
| Data GATT writes | 570 | 456 |
| Data HCI ACL packets | 3,990 | 4,275 |

Both transferred the exact same 102,846-byte / 800×800 / quality 87 prepared JPEG, SHA-256
`867ca28e128bd60149a33d719646ab649c12d4d45d62e0b104e4ec1dda32f878`, identical decoded RGB.
All 57 indexes, ACKs, checksums and zero padding matched. Square flip false. User confirmed the
second film was upright, unmirrored and had the same colour/detail as the first. Film 3→2→1.
Other models have unit coverage, not new physical film verification.

244 reduced GATT writes but was slower. The Pi controller exposes 27-byte LE buffers and no Data
Length Extension feature; related length commands return Unknown HCI Command. The full 1819-byte
Square packet takes 70 HCI packets at 182, 75 at 244, and 70 at 236. Hence 236 is the production
ceiling. HCI captures do not measure radio retransmissions, battery energy or general runtime.

## Same-connection no-film crossover

Two rounds each of 182, 244 and 236, same prepared JPEG / connection / 1000 MHz. Each download
ends with an exact Cancel ACK; no PrintImage command. Six Start/End/Cancel pairs, 342 ordered Data
ACKs, identical JPEG hashes; film remains 1 and history remains 67.

| Payload | Mean download/cancel | Data GATT writes |
|---|---:|---:|
| 182 | 21.896 s | 570 |
| 244 | 22.784 s | 456 |
| 236 | 21.778 s | 456 |

236 saves 20% of GATT writes and only 0.117 s (~0.54%) in these two samples. This is a small
transport improvement, not a measured large full-print speedup. All 1,388 clock samples were
1000 MHz. The remaining ~8.9 s of post-ACK pacing and controller/write scheduling dominate.
Shortening model-specific pacing needs separate reliability evidence and is outside this change.
SD cache does not address this transport bottleneck.

The original crossover completed counters but exited with a teardown Timeout before its JSON
was emitted. HCI capture independently verifies completed measurements; retained JSON explicitly
records that nonzero exit. Physical Disconnect was never dispatched after StopNotify. The fix
attempts bounded physical disconnect first and verifies authoritative disconnected state; it
closes the old transport and marks reset before any await. Cancellation preserves reset, and
forced reset skips a potentially stuck preliminary state query. The diagnostic now prints
completed rows and separate benchmark/cleanup errors before returning nonzero on either failure.

## Validation and deployment

Independent tests cover MTU bounds/identity ambiguity, bytes and padding for every model, lock
serialization, partial-write/no-ACK/cancellation poisoning, bounded D-Bus resources and recovery
cache, no replay, teardown RPC failure/timeout/cancellation, and retained diagnostic results.
Rust workspace 245 tests, build/fmt/Clippy, App 156 tests and strict docs passed. All 44
independent transport/diagnostic tests also passed on the Pi arm64. Adversarial final review
found no remaining P1/P2 issue. Final hardware teardown and clean artifact deployment are recorded in the Bridge context and
sanitized assets after verification.

Evidence: `docs/assets/bridge-audit-073/physical-{baseline,candidate}.json`,
`download-crossover.json`, `controller.json`. Personal pixels and raw Bluetooth captures are not
committed. Sources: [BlueZ characteristic API](https://raw.githubusercontent.com/bluez/bluez/5.82/doc/org.bluez.GattCharacteristic.rst),
[Bluetooth Link Layer](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core-54/out/en/low-energy-controller/link-layer-specification.html).
