# 071 — Prepared JPEG native handoff

Date: 2026-10-12. Three agents implemented native validation/FFI, Bridge preparation/handoff,
and independent adversarial tests. Root benchmarked real HIF-derived payloads on the Pi.

## Implementation and compatibility

The Bridge now hands its final JPEG to three additive prepared-JPEG FFI exports. Core owns
validation and the existing serialized Printer transaction; the App's file-based ABI remains
unchanged. No public management/sync API, settings, protocol delays or App/iOS code changes.

- Require exact detected model, including Mini versus Mini Link 3 despite identical dimensions.
  Model configuration is a preparation hint; mismatch discards speculative preparation.
- Require the model's exact dimensions and byte limit, 8-bit three-component baseline JPEG,
  complete entropy scan, neutral recognized EXIF orientation and no trailing data.
- Apply Mini Link 3's vertical transport flip before the final Python JPEG encode. Reverse it
  only for the LCD preview. Mini/Square/Wide preserve their prior JPEG and pixels. The lossless
  working cache remains before the transport flip and is reused by edits.
- Feature-detect the optional native export off the UI loop. Older native builds prepare an
  unflipped JPEG and retain the legacy file path; stale Link 3 output is rebuilt from its source.
- Keep the in-memory ctypes buffer and callback alive through the synchronous native operation,
  including repeated outer cancellation. Release global FFI device ownership before callbacks;
  retain the per-Printer operation lock through the transaction. No fallback/resend after errors.
- Validate before every Printer write and transmit the exact supplied JPEG bytes. A bounded
  decode checks integrity but does not resize, correct colour or encode again.

See [the FFI contract](../reference/ffi.md) for model IDs, return codes and buffer/callback rules.

## Adversarial review and repairs

Independent tests reproduced a half-truncated entropy scan with EOI restored being accepted by
both attempted Rust decoders, which recovered missing pixels even in strict mode. The final
validator uses an owned per-call libjpeg-turbo handle with STOPONWARNING enabled and checks
header parameters before bounded allocation. Quarter/half/three-quarter truncations with EOI
restored now fail. TurboJPEG is statically bundled through turbojpeg-sys; CMake/compiler and
x86 NASM prerequisites are documented and installed in CI. No new Pi runtime package is needed.
[Upstream TurboJPEG API](https://github.com/libjpeg-turbo/libjpeg-turbo/blob/main/src/turbojpeg.h).

Independent tests cover exact model/flip, byte limit/dimensions, grayscale, CMYK, PNG,
progressive/trailing JPEG, EXIF orientation, corrupt entropy and no Printer writes on rejection.
Bridge tests cover upright previews, exact prepared bytes/flag/model, old-library compatibility,
no resend on native failure and buffer/lock lifetime under repeated cancellation. Final review
has no remaining actionable P1/P2 issue. All nine independent native tests also ran on arm64 Pi.

The full Bridge suite exposed an existing FTP test timing race: queue handoff can precede the
callback's ownership-release finally. A same-connection NOOP after 226 orders terminal assertions
without weakening overlap/rejection/byte checks. The test fixture now closes its event loop on
its serving thread. This tests-only fix passed 300 stress cases with zero BadFD teardown noise
and an independent second review. Production FTP code is unchanged.

## On-Pi benchmark

Pi Zero 2 W Rev 1.0, stock 1000 MHz (every sampled frequency checked), Debian 13.2,
Linux 6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82, Bridge 0.1.17. ST7789 LCD and
X306 2300 mAh battery; Sony a7C II profile, saved Instax Square INSTAX-52006924.

The real 11,255,808-byte HIF has primary dimensions 7008×4672. Saved Auto fit, Vivid
saturation 1.5 and neutral Correction were retained. Requested quality 100 is reduced by each
model's existing size budget to Mini 80 / Link 3 42 / Square 76 / Wide 85. Both native paths
were built in the same arm64 release. Five interleaved measurements per model compare legacy
native decode/resize/encode/chunk with strict validation/chunking of the final Python JPEG.
Times below are medians; they exclude Python preparation, BLE, ACKs and mechanical ejection.

| Model | Legacy native preparation | Prepared validation/chunk | Time reduction | JPEG bytes | Chunks |
| --- | --- | --- | --- | --- | --- |
| mini | 738.49 ms | 13.47 ms | 98.18% | 104,154 → 102,631 | 116 → 115 |
| mini_link3 | 612.31 ms | 10.78 ms | 98.24% | 54,224 → 54,498 | 61 → 61 |
| square | 943.30 ms | 15.56 ms | 98.35% | 104,628 → 102,303 | 58 → 57 |
| wide | 1609.59 ms | 28.87 ms | 98.21% | 223,131 → 217,375 | 248 → 242 |

All prepared output JPEG hashes match their Python inputs exactly. Square preserves the prior
102,303-byte reference JPEG and RGB hashes. This removes a lossy generation; the new pixels
need not equal the old native re-encoded pixels. Link 3 flips once before encoding, so its JPEG
can differ slightly from flip-after-decoding an earlier lossy generation; asymmetric-image
orientation tests check semantics, not equality with the old lossy result.

The Square native preparation saves about 0.928 seconds. Its one fewer packet, and Wide's six
fewer packets, also reduce configured packet sleeps by 0.15/0.90 seconds respectively; those
are code-derived opportunities, not measured physical print totals. First HIF preparation
still takes 3.86–6.24 seconds across models, with decode remaining the main first-photo cost.
No new SD cache is introduced; the active lossless source remains in tmpfs.

[Full benchmark, byte/RGB hashes, pixel differences, clock samples and settings](../assets/bridge-audit-071/native-preparation.json).
No throttling (0x0); benchmark restores powersave at completion and removes temporary JPEGs/cache.

## Validation and deployment

- Rust workspace: 205 passing tests (25 CLI, 134 core, 9 independent integration, 36 FFI,
  one doc test), build, formatting, Clippy with warnings denied and committed-header drift check.
- Bridge: 1,497 tests, Ruff, touched-file formatting and strict mypy (65 source files).
- App harness: 156 tests; existing file-based ABI reviewed for compatibility.
- Nine independent native tests passed on the Pi (2.10 seconds).

Clean code commit **`6ca7035`** was pushed and deployed with newly built arm64 CLI/FFI artifacts.
[Native provenance](../assets/bridge-audit-071/native-provenance.json) records that source commit,
`dirty=false`, locked release build and artifact hashes. Installed FFI SHA-256:
`8d5ee8081dc297f9c588038410941433d3f72a5eebe9b8c5f688dad476e5f75d`.
All three exports are present. The validator has no new dynamic JPEG dependency on the Pi.

[Installed production worker/ctypes smoke](../assets/bridge-audit-071/installed-handoff.json)
passed for all four models using an asymmetric synthetic image: correct dimensions/budget,
exact in-memory bytes/model/flip, upright decoded LCD render and Link 3-only transport flip.
The actual C export rejects null/zero/invalid declarations with -5 and valid calls with -1
in its separate no-device process. Connect/model lookup were observed at the Python boundary;
no actual BLE connection, connected transaction, progress dispatch or physical LCD was tested
by that smoke. The separate nine native arm64 integration tests cover strict JPEG validation
and transaction rejection. No film was consumed.

[Post-deploy health](../assets/bridge-audit-071/installed-health.json): Bridge/manager active,
NRestarts=0, hotspot 192.168.8.1 and USB 192.168.7.1, FTP greeting 220 / NOOP 200,
dark powersave 600 MHz, GPIO24 low, throttling 0x0 and zero working cache directories.
Python/Pillow/pillow-heif/pyftpdlib versions are unchanged. Temporary candidate libraries,
benchmark binaries, source overlays and probes are removed after verification.
Subsequent documentation-only deployment carries identical verified runtime code and artifacts.
The saved Printer is not advertising, so physical BLE/film speed and colour remain unmeasured.
