# Ten-area repository performance audit

## Request and execution window

Run ten Astra subagents over a two-hour work window beginning 2026-10-15 05:27 UTC
(01:27 America/New_York), targeting completion by 07:27 UTC. At most three subagents run alongside
the primary agent because the session has four total agent slots. Each agent audits a distinct
area, implements one useful optimization and reports measurements and correctness limits.

Use the managed checkout on `codex/performance-audit-ten`, starting from merged main `f5ed2c8`.
Do not use film or change the installed Bridge. Preserve product behavior, image quality,
orientation, upload/reconnect/cancellation semantics, API/ABI contracts and security. Existing
hardware validation is not evidence for new changes. Any hardware-specific result remains
explicitly unverified until a later device check.

## Ten independent areas

1. Rust image preparation.
2. Rust protocol/packet processing.
3. Bridge FTP upload/housekeeping.
4. Bridge sync outbox/storage.
5. Bridge management diagnostics/status.
6. Bridge network health/snapshots.
7. Bridge postprocessing.
8. App image/editor processing.
9. App Bridge transport/data handling.
10. iOS app sync/client persistence.

Agents own disjoint production files. Root integrates, independently reviews changes and runs
the applicable path-scoped repository gates. Before/after measurements must identify workloads,
output equality/behavior assertions, sample count and environment; avoid general speed or battery
claims from microbenchmarks. Reject ineffective candidates and find alternatives within the area.
Do not invent ten gains to fill a count; record any area without an accepted improvement.

## Final acceptance

Record one result per area, exact validation, adversarial findings/fixes and remaining risks.
Keep the working changes reviewable on the dedicated branch; no merge or hardware deployment is
implied by this audit request. All final validation and source state are reported at handoff.

## Integration review

The primary agent independently reviews each production diff against merged main. Acceptance
requires preserving behavior and demonstrating a gain in the affected stage, rather than a
particular whole-application speedup.

| Area | Review focus |
| --- | --- |
| Rust image preparation | RGB8-only copy, empty axes, logical buffer bounds, unchanged conversion fallback, exact JPEG/chunks and model flips |
| Rust packet processing | Existing header/length/checksum validation dominates extraction, identical drain/error ordering and partial-tail handling |
| FTP housekeeping | Canonical strings preserve POSIX path equality; retain original scan and both metadata-error phases; unchanged deletion ownership and budget accounting |
| Sync outbox | Immutable scalar projection, exact persisted bytes and field order, atomic publication and failure cleanup untouched |
| Diagnostics | Hash the closed archive, propagate read failures, close descriptor, retain redaction and metadata; disclose fixed-buffer small-file cost |
| Network snapshots | Packed IPv4 tuple preserves host bits and every prefix; validation, fresh reads and fallback remain intact |
| Bridge hue | Exact pointwise sector math, private quantization buffer, complete 2D tile coverage, empty/non-RGB fallback and unchanged metadata behavior |
| App editor | Identical LUT bytes and Double transfer results, local prepared coefficients, unchanged filter/color space and concurrency |
| App firmware | Bounded reads, descriptor closure and fail-closed errors; retain every artifact/path/schema/signature-presence check on every invocation |
| iOS sync | Accepted restart/resume offsets, terminal/error progress, stale UI task rejection, unchanged checksum/backpressure and save-before-ACK paths |

Initial workspace gates: Rust build, Clippy with warnings denied, all 349 Rust tests and FFI header
drift passed; one opt-in benchmark is ignored by the normal test suite. The host lacks the normal
vendored JPEG build prerequisites, so builds use its existing Homebrew static JPEG library through
the documented `TURBOJPEG_*` environment variables. No build dependency was added.

## Agent execution and corrections

Ten unique agents used `gpt-6-astra`, each with a distinct implementation area:
`perf01_rust_images`, `perf02_rust_protocol`, `perf03_bridge_ftp`,
`perf04_bridge_outbox`, `perf05_bridge_diagnostics`, `perf06_bridge_network`,
`perf07_bridge_postprocess`, `perf08_app_imaging`, `perf09_app_firmware`,
and `perf10_ios_sync`. The session ran at most three alongside the primary agent.
Finished agents 02 and 09 were reused for cross-review, and agent 07 refined its
original hue optimization to bound memory; no eleventh agent was spawned.

Corrections made during this audit:

- Reject FTP `scandir` variants that increased CPU cost or changed permission-error
  phases. Keep the original file classification and fresh second metadata lookup.
- Bound RGB row copies to logical image height so oversized backing storage cannot
  enter white padding.
- Replace the initial hue allocation reduction with bounded two-axis tiling; the
  initial 8 MP candidate still exceeded the Pi's RAM in host allocation measurements.
  Exact arithmetic, pixels and JPEG output remain preserved.
- Fix iOS retry progress before acceptance: preserve previously visible partial bytes
  on header failure, allow a successful 200 response to reset progress, and reject
  delayed callbacks from completed or forgotten attempts.
- Fix two FTP tests that mocked Python 3.13's internal enumeration implementation.
  Inject at `Path.iterdir` instead; the older enumeration-boundary reproduction now
  passes both tests. Actual Python 3.11/3.12 execution remains unperformed.
- Apply the Bridge's explicit Ruff configuration to all Python benchmark helpers.

Independent review records and per-area benchmark reports are linked from the
[evidence index](../assets/performance-audit-099/README.md). No actionable production
regression remains from those reviews. Host software validation cannot replace a
later physical Bridge/Printer check, and no film was used.

## Final validation and outcome

All ten areas have an accepted optimization with reproducible measurements and
equivalence/regression coverage. The primary agent reviewed every production diff;
independent cross-review covered Rust, the Bridge, App imaging and iOS. The two
reported correctness/portability findings were corrected before acceptance.

| Gate | Result |
| --- | --- |
| `cargo build --workspace --locked` | Passed with the existing explicit JPEG library |
| `cargo fmt --all -- --check` | Passed |
| `cargo clippy --workspace --locked -- -D warnings` | Passed |
| `cargo test --workspace --locked` | 349 passed; one opt-in benchmark ignored |
| `bash scripts/check-ffi-header.sh` | Passed; no ABI/header change |
| Bridge `ruff format --check src tests` | 168 files formatted |
| Bridge `ruff check src tests` | Passed from the canonical `bridge/` working directory |
| Bridge `mypy src` | Passed, 70 source files |
| Bridge `pytest -q` after tiled refinement and portability fix | 3,196 passed; eight expected non-Pi GPIO fallback warnings |
| `bash scripts/test-macos.sh` | 165 passed, zero failed; existing Combine import warnings only |
| iOS XcodeGen + simulator `xcodebuild test` | 51 executed, zero failures, one existing unavailable-Keychain skip |
| Python benchmark helpers, explicit Bridge Ruff config | Eight helpers pass lint and format checks |
| `bash -n scripts/test-macos.sh` / Git whitespace checks | Passed |
| MkDocs strict build to a temporary site directory | Passed |
| Localization checker | Fails on the same 270 baseline missing English keys; output is byte-identical to the pre-change run |

iOS validation used iPhone 17 / iOS 27.0 simulator
`657CB222-AE66-4F0E-9783-431CE286072C`, with `CODE_SIGNING_ALLOWED=NO`.
Mac software rendering and filesystem validation used Apple M3 Max / macOS 27.0.1,
with an arm64 macOS 15.0 deployment target. No actual macOS 15 host, physical iPhone,
camera upload, Bluetooth connection, GPIO/LCD, firmware installation or film test
was performed in this source audit.

The path-scoped Git hooks passed for all source commits. The initial final Bridge
hook attempt caught test import ordering despite all 3,196 tests passing; the
import order was corrected and the full required hook rerun successfully.

Source commits:

- `0374fba`: Rust image composition and packet assembly.
- `4ebbb32`: App LUT construction and firmware hashing.
- `ca9299b`: Bridge FTP, sync, diagnostics, network and tiled hue processing.
- `8a9515a`: iOS progress delivery and retry state.

Work is retained on `codex/performance-audit-ten` for review. No merge or device
deployment is part of this audit. Host microbenchmarks do not establish total
printing latency, battery runtime or physical Pi memory use. Source implementation,
benchmarks and validation completed within the requested two-hour window.
