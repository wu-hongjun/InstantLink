# 02 — Rust protocol packet assembly

## Change and preserved behavior

`PacketAssembler::feed` already validates header, declared length, and checksum before its success branch. Previously that branch drained the entire packet into a temporary `Vec`, called `parse_packet`, repeated validation/checksum, and allocated a second `Vec` for the payload. It now copies the validated payload directly into the returned `Packet`, then drains the same declared number of bytes. The public parser, encoder, commands, checksum, fragmentation, error branches, API, and dependencies are unchanged.

This removes one allocation per complete packet (including empty payload packets), one full packet copy, and one checksum pass. It does not alter notification buffering, concatenated packet handling, error ordering, discarded-byte counts, cancellation, serialization, MTU selection, or emitted bytes.

## Measurement

Host: Apple M3 Max, arm64 macOS 27.0.1 (26A434). Rust: `rustc 1.96.0 (ac68faa20 2026-05-25) (Homebrew)`. Measurement date: 2026-10-15. Baseline protocol implementation: commit `f5ed2c8`; optimized implementation: this change.

The committed `crates/instantlink-core/examples/protocol_assembly_benchmark.rs` invokes the actual production `build_packet`, `parse_packet`, and `PacketAssembler`, with equality assertions before timing. It reuses an assembler with warmed buffer capacity, feeds 182-byte fragments, and drops each result. There is no duplicated packet implementation or Bluetooth access. Empty, indexed ACK-sized, and status-sized packets represent small responses; 1 KiB and the maximum legal payload are fragmentation stress cases rather than a claim about typical response sizes.

Each executable runs 1,000 warmups and nine timing samples per workload. A sample processes 500,000 small packets, 100,000 1 KiB packets, or 2,000 maximum packets. Before/after executables were preserved separately, compiled before timing, and run in counterbalanced A/B/B/A order under an exclusive `fcntl.flock` on `/tmp/instantlink-099-benchmark.lock`, coordinated with other audit agents. There are 18 timing samples per version/workload across two processes. The initial uncoordinated build/run was excluded.

| Workload | Before median ns/packet, runs A1 / A2 | After median ns/packet, runs B1 / B2 | Warm allocations before → after |
| --- | ---: | ---: | ---: |
| Empty response | 55.95 / 51.63 | 11.85 / 16.19 | 1 → 0 |
| 5-byte indexed ACK | 89.08 / 80.90 | 36.92 / 53.02 | 2 → 1 |
| 18-byte status response | 87.68 / 89.71 | 35.41 / 64.26 | 2 → 1 |
| Fragmented 1 KiB | 186.85 / 178.54 | 106.68 / 177.11 | 2 → 1 |
| Maximum 65,528-byte payload | 8631.23 / 9615.83 | 5518.38 / 6441.27 | 2 → 1 |

All paired process medians improved; the 1 KiB second pair is nearly flat. Allocation counts are measured with a global allocator counter after buffer warmup. Timings include that counter's atomic increment, so some timing savings include avoided instrumentation. Shared-machine scheduling/frequency/load caused substantial dispersion even with benchmark serialization; these are local CPU microbenchmarks, not an end-to-end BLE, print-time, energy, or Bridge performance claim. The deterministic allocation and redundant-work removal support the result without requiring a particular percentage speedup.

## Reproduction

Run the identical benchmark helper on the baseline and changed production sources, preserving each resulting executable before the next build:

```sh
TURBOJPEG_SOURCE=explicit \
TURBOJPEG_LIB_DIR=/opt/homebrew/opt/jpeg-turbo/lib \
TURBOJPEG_INCLUDE_DIR=/opt/homebrew/opt/jpeg-turbo/include \
TURBOJPEG_STATIC=1 \
cargo build -p instantlink-core --release --locked --example protocol_assembly_benchmark
```

The JPEG environment variables select the already installed Homebrew library because this host lacks CMake; they are unrelated to the protocol benchmark. No dependency was installed or changed. On a host with the normal bundled JPEG build prerequisites, they can be omitted. Copy `target/release/examples/protocol_assembly_benchmark` to separate before/after paths. Execute before, after, after, before while holding the shared lock. Keep all builds outside the timed region. The helper prints per-process min/median/max and warm allocation counts.

## Verification

Completed with the JPEG environment shown above:

- `cargo test -p instantlink-core --locked protocol::tests --lib` — 28 passed.
- `cargo test -p instantlink-core --locked --test mtu_fragmentation` — 11 passed.
- `rustfmt --edition 2024 --check crates/instantlink-core/src/protocol.rs crates/instantlink-core/examples/protocol_assembly_benchmark.rs` — passed.
- `git diff --check -- crates/instantlink-core/src/protocol.rs crates/instantlink-core/examples/protocol_assembly_benchmark.rs docs/assets/performance-audit-099/02-rust-protocol.md` — passed.

Five new regression tests exercise both request and response headers; empty through maximum payload sizes; byte-at-a-time and MTU-bound fragments; empty feeds; every split position of a concatenated stream with a trailing partial packet; malformed declared lengths 0–6 with exact original buffer lengths and discard counts; bad checksums with a valid following packet; and false potential header bytes during resynchronization. The existing MTU integration suite verifies wire equality, all model packet fragmentation, cancellation, failure behavior, and operation serialization.

No Printer, Bridge, camera, BLE connection, SSH session, or film was used. A hardware smoke test was not performed; this change is limited to validated in-memory packet extraction. Root workspace gates are reported by the audit coordinator.

## Raw counterbalanced output

```text
before
empty-response: payload=0 fragment=182 iterations=500000 allocations/packet=1 ns/packet min=46.75 median=55.95 max=113.17
indexed-ack: payload=5 fragment=182 iterations=500000 allocations/packet=2 ns/packet min=63.71 median=89.08 max=437.09
status-response: payload=18 fragment=182 iterations=500000 allocations/packet=2 ns/packet min=73.73 median=87.68 max=94.91
fragmented-1KiB: payload=1024 fragment=182 iterations=100000 allocations/packet=2 ns/packet min=174.76 median=186.85 max=191.01
max-packet-stress: payload=65528 fragment=182 iterations=2000 allocations/packet=2 ns/packet min=8301.27 median=8631.23 max=9108.50

after
empty-response: payload=0 fragment=182 iterations=500000 allocations/packet=0 ns/packet min=11.83 median=11.85 max=11.92
indexed-ack: payload=5 fragment=182 iterations=500000 allocations/packet=1 ns/packet min=35.86 median=36.92 max=38.49
status-response: payload=18 fragment=182 iterations=500000 allocations/packet=1 ns/packet min=34.04 median=35.41 max=37.77
fragmented-1KiB: payload=1024 fragment=182 iterations=100000 allocations/packet=1 ns/packet min=99.30 median=106.68 max=109.01
max-packet-stress: payload=65528 fragment=182 iterations=2000 allocations/packet=1 ns/packet min=5429.35 median=5518.38 max=8532.10

after
empty-response: payload=0 fragment=182 iterations=500000 allocations/packet=0 ns/packet min=15.07 median=16.19 max=26.68
indexed-ack: payload=5 fragment=182 iterations=500000 allocations/packet=1 ns/packet min=45.80 median=53.02 max=58.61
status-response: payload=18 fragment=182 iterations=500000 allocations/packet=1 ns/packet min=40.76 median=64.26 max=78.04
fragmented-1KiB: payload=1024 fragment=182 iterations=100000 allocations/packet=1 ns/packet min=121.96 median=177.11 max=217.47
max-packet-stress: payload=65528 fragment=182 iterations=2000 allocations/packet=1 ns/packet min=5917.27 median=6441.27 max=7949.25

before
empty-response: payload=0 fragment=182 iterations=500000 allocations/packet=1 ns/packet min=47.53 median=51.63 max=60.70
indexed-ack: payload=5 fragment=182 iterations=500000 allocations/packet=2 ns/packet min=70.61 median=80.90 max=142.31
status-response: payload=18 fragment=182 iterations=500000 allocations/packet=2 ns/packet min=86.82 median=89.71 max=103.91
fragmented-1KiB: payload=1024 fragment=182 iterations=100000 allocations/packet=2 ns/packet min=176.67 median=178.54 max=179.26
max-packet-stress: payload=65528 fragment=182 iterations=2000 allocations/packet=2 ns/packet min=8875.73 median=9615.83 max=13096.92
```
