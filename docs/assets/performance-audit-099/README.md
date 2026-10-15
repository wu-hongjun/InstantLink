# Ten-aspect performance audit evidence

Base: merged main `f5ed2c8037511483299c56c3bc71cdaef3d661cc`. Work branch:
`codex/performance-audit-ten`. Requested window 2026-10-15 05:27–07:27 UTC
(01:27–03:27 America/New_York). Ten Astra subagents run in batches, at most 3 concurrent.

Host: Apple M3 Max, macOS 27.0.1/build 26A434, Python 3.13.9, Rust 1.96.0,
Swift 6.4; macOS App target remains arm64/macOS 15.0. Root uses the pinned Bridge developer venv.
Rust local compilation uses existing Homebrew jpeg-turbo via explicit library/include paths;
no package install or dependency change. Timing runs use an exclusive benchmark lock and
counterbalanced samples where practical; compilation/other machine load is separately scoped.
No Pi, camera or Printer commands, image dispatch or film. No deployment is performed.
Host microbenchmarks do not establish Pi performance, battery life or full printing latency.

## Baseline gates

The unchanged baseline App harness passes 156 tests. Swift 6.4 emits existing missing-Combine-import
warnings in BridgePairingView. Baseline localization checker fails on existing missing English
keys; its output is retained privately. New performance work must introduce no localization keys
or worsen that baseline. Applicable final gates and any failures will be recorded after integration.

## Results

Ten distinct Astra agents implemented the following optimizations. Finished agents were reused
for independent cross-review; no additional audit agents were created. Each result below applies
to the named stage and fixture, not whole-application speed or Raspberry Pi performance.

| Area | Accepted optimization | Measured result | Evidence |
| --- | --- | --- | --- |
| Rust images | Copy opaque RGB8 Contain rows | Native composition 4.258 → 0.130 ms; exact pixels/JPEG | [01](01-rust-images.md) |
| Rust packets | Extract already validated payload directly | Warm response allocations 2 → 1; empty response 1 → 0 | [02](02-rust-protocol.md) |
| Bridge FTP | Canonical string retention comparisons | 100-file sweep CPU 1.103 → 0.955 ms | [03](03-bridge-ftp.md) |
| Bridge sync | Serialize immutable index scalars directly | 1,024-item publication 3.169 → 1.817 ms | [04](04-bridge-outbox.md) |
| Bridge diagnostics | Stream completed ZIP hashing | 33.4 MB ZIP hashing allocation 33.36 → 0.268 MB | [05](05-bridge-diagnostics.md) |
| Bridge network | Construct IPv4 interfaces from packed bytes | Three-address parser CPU 41.13 → 28.48 µs | [06](06-bridge-network.md) |
| Bridge postprocessing | Bound hue intermediates to 512 × 256 RGB tiles | 8 MP tracked peak 762.8 → 10.8 MiB; CPU 403.9 → 365.0 ms | [07](07-bridge-postprocess.md) |
| App editor | Prepare Levels coefficients and pack LUT directly | Combined LUT thread CPU 55.001 → 44.925 µs | [08](08-app-imaging.md) |
| App firmware | Hash artifacts in 1 MiB chunks | 256 MiB archive validator RSS 262.47 → 8.58 MiB | [09](09-app-firmware.md) |
| iOS sync | Bound progress delivery to 100 ms intervals | 1,600 fast-chunk callbacks → 17; final count preserved | [10](10-ios-sync.md) |

Every report includes reproduction, fixture/sample counts, raw results or their location,
equivalence checks, environment and limits. Wall timings were sometimes noisy; reports distinguish
CPU time, allocation counts, traced memory, process RSS and inconclusive measurements.
The diagnostics hash uses more temporary memory for very small ZIPs. Slow iOS streams receive
one extra initial-offset callback, and suppressed trailing progress waits for the next chunk or
terminal event. These tradeoffs are recorded alongside the measured benefits.

The hue refinement was required because the first accepted vectorized version still used too
much memory at 8 MP. Final isolated host RSS is 223.2 MiB including imports, input and output;
this does not establish total Bridge memory or prove that a physical Pi workload fits its RAM.

## Independent reviews and corrections

- [Rust and App imaging](review-rust-app.md): bounds, packet extraction, alpha fallback,
  exact LUT arithmetic, reference oracles and concurrency.
- [Bridge](review-bridge.md): retention/error phases, ownership, atomic JSON publication,
  hashing and network freshness. Review found two Python-version-dependent test injections;
  both were moved to the stable `Path.iterdir` boundary.
- [iOS](review-ios.md): restart/resume offsets, terminal counts, queued UI work, cancellation,
  completed-file integrity and save-before-ACK ordering.
- [Tiled hue](review-hue.md): independent oracle identity, exact pointwise arithmetic,
  full tile coverage, fallback behavior and memory measurement definitions.
- Primary review caught and corrected an iOS retry display regression before final validation:
  preserve known partial progress until an accepted response establishes restart or resume.

Primary integration decisions and final validation are recorded in
[plan 099](../../plans/099-repository-performance-audit.md).

Final suites: **349 Rust tests**, **3,196 Bridge tests**, **165 App tests**, and
**51 iOS tests executed with zero failures and one existing Keychain skip**.
The normal Rust run ignores one opt-in benchmark. Formatting, lint, type checking,
header drift and strict documentation checks pass. The localization checker retains
its unchanged baseline failure; no localization strings were changed.
