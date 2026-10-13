# Bridge native Bluetooth discovery

## Goal and baseline

Reduce repeated Linux discovery work while preserving automatic Printer reconnect,
unfiltered scanning, model detection, scan cleanup and existing candidate checks.
All hardware checks in this work use no film.

The installed Bridge, dark at 600 MHz with the Printer offline, measured 1.499%,
2.631% and 1.499% of one core in three 30-second intervals, with zero child CPU.
A separate 36-second D-Bus diagnostic found 12 native ObjectManager queries and
225 native Device1 GetAll queries. Cached unrelated devices are queried on each
400 ms discovery poll. One additional ObjectManager query belonged to Python
recovery. Tracing is excluded from accepted CPU intervals.

## Implementation boundaries

Keep btleplug's selected-adapter peripheral handles. Read a second fresh bulk BlueZ
snapshot and skip only records with valid metadata that identifies no Instax name
or service. Possible Printers still use the existing fresh properties, Android
exclusion and Linux RSSI/connected evidence checks. Missing, malformed or removed
records use the original per-device path; unavailable bulk data uses the complete
original path. Snapshots are never cached across polls.

Reuse an owned D-Bus connection with a 500 ms overall acquisition/open/query
budget. Cancellation drops the caller's resource; a mutex waiter cannot invalidate
another caller. A stalled blocking connection open holds its semaphore permit
until completion. The reader never starts or stops discovery.

No dependency, FFI, settings, image, fragment, pacing, CPU-tier or UI change.
The extra snapshot is not atomic with BlueZ property updates: a name/service arriving
after the prefilter is observed by the next poll. One-shot scan results retain a
boundary at their final collection time.

## Validation

- Independent implementation, source research and adversarial review.
- Linux parser and asynchronous ownership/cancellation regression coverage,
  executed in the ARM64 Rust test binary on the Bridge.
- Host Rust workspace, formatting, Clippy, FFI header and App checks.
- Real-device native query counts and baseline/candidate CPU intervals with tracing separated.
- Status-only reconnect, scan cleanup and normal installed-service health.
- Clean source/artifact manifests, native CLI/FFI deployment and removal of temporary
  test resources. Record all measurements, fallback behavior and test limitations.

## Primary references

- [Pinned bluez-async implementation](https://docs.rs/bluez-async/0.8.2/src/bluez_async/lib.rs.html)
- [BlueZ Device1 contract](https://bluez.readthedocs.io/en/latest/device-api/)
- [BlueZ discovery contract](https://bluez.readthedocs.io/en/latest/adapter-api/)

## Candidate results

- Actual ARM64 unit binary on the Pi: **183 passed**, including **14** discovery
  regression cases. Independent ARM64 container execution passed all 14. The wire
  test roundtrips a real D-Bus message rather than assuming fixture array types.
- Host workspace: **282** tests, strict Clippy, locked build, formatting and FFI
  header checks passed; App **156** tests passed. Linux production Clippy is strict;
  Linux test-target Clippy allows two existing Rust 1.97 test-only lint findings
  (`new_ret_no_self`, `items_after_test_module`). No new-module lint findings.
- Three native five-second named searches per build: baseline mean CPU **0.526 s**,
  candidate **0.465 s**; mean elapsed **5.413 / 5.375 s**. All returned the expected
  missing-name error and stopped scanning; descriptors stabilized at 11/12 after
  first initialization. Candidate owns one additional reused snapshot connection.
- Separate 36-second candidate diagnostic: **15** btleplug bulk reads, **14** fresh
  prefilter bulk reads, **zero** Device1 GetAll calls, one Python recovery bulk read.
  Baseline had 12 native bulk / 225 individual reads. Cached/ambient devices and poll
  counts vary; raw identities remain private.
- Full-runtime baseline/candidate means **1.876 / 1.266%** of one core, three
  30-second intervals each, Printer offline/dark/600 MHz, zero child CPU. The observed
  difference is **32.5%**; separate process starts and ambient BLE prevent a general
  CPU or energy claim. Trace and Rust test execution occur outside CPU intervals.
- Rejected attempts are recorded in validation evidence: initial CPU timing began
  before auto-lock, mixed local Rust toolchains failed Clippy, and an ARM test link
  exhausted Mac disk space. No failed timing row was accepted. Matching Clippy and
  removing this task's disposable header-build cache resolved build failures.

- Eleven kernel-to-production-UI cases passed with the candidate FFI, actual LCD
  and CPU tiers. First press during startup was ignored by the existing startup
  guard; rerun after settle passed. Physical button contacts were not actuated.
- Printer power-return reconnect succeeded while locked. A controlled Device1
  disconnect exceeded a 65-second harness deadline, then the same process recovered
  automatically; both observations are retained. Source review found unchanged
  cached-session/command-lock/timeout/retry policies, with no prefilter-specific
  concern. INFO logs do not establish a radio cause or an exact delay breakdown.
  Short forced-disconnect recovery is not claimed; status-lock/retry latency remains
  a separate optimization candidate.
