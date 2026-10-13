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

## Recovery defect found by hardware testing

The 180-second Bluetooth daemon restart check did not pass. The later shutdown
journal showed `bluetooth.agent_unregister_failed`, ending in BlueZ `Does Not Exist`.
The process still held `_registered=True` even though the restarted daemon had lost
its pairing agent. This is a concrete lifecycle defect, separate from the unproven
radio cause of individual status failures. The full service log capture contains
2592 records; the temporary candidate process has 225 INFO, 25 WARNING and one ERROR.
The error is a production agent lifecycle error, not an observer writer failure.

Extend this work with event-driven owner tracking on the existing Python agent bus.
An awaited match rule and handler precede the initial owner query. Registration uses
fresh proxies addressed to the current unique owner, owned bounded retry tasks and
checks after awaits. Owner loss clears readiness immediately. Shutdown removes its
handler/tasks, unregisters the current partial/full registration, and closes its bus;
BlueZ's expected missing-agent reply is handled narrowly. No idle polling or process
launches are added. Test daemon absence/return, repeated signals, partial registration,
owner/stop races and snapshot reply freshness, then rerun the real restart gate.

The native optimization itself is clean **a8b637c**, pushed and installed. Native FFI
SHA-256 `fdd47eaddb35f630534b5f250c8810515c5c14ac0ad5a68fa46a83f46f185973`;
CLI `3744699d034ab1870e563bbca2c3aad88aff43f0485097ae6bf929595d051cee`.
Both baseline and candidate ELF comments identify Rust 1.97.1 and the same compiler
and linker versions. Installed normal PID16829 / manager16827 are active, NRestarts0,
dark600MHz, FTP220/200 and no current application WARNING/ERROR; Printer offline
at that capture. A fresh installed Printer check and agent-recovery deployment remain.

## Agent repair acceptance

- Independent review passed **83** focused Python cases. Full Bridge suite **1672**,
  Ruff and strict mypy **67** source files passed; the 27 test warnings are expected
  host GPIO fallback/deprecation warnings. Cancellation review caught cleanup gaps
  before deployment; owned shielded cleanup and tests resolve them. Late interface
  readiness is event-driven after a bounded retry window, avoiding permanent polling.
- Candidate actual Pi: **three** Bluetooth daemon restarts re-registered the agent
  in **1.000 / 0.774 / 0.782 s** from command start, same PID17231 and same Python
  bus connection. Every observed state remained locked600MHz and camera-ready;
  registration tasks were empty afterward. These are agent-registration timings,
  not three Printer reconnect timings. Eleven kernel-to-UI cases passed again.
- The installed native firmware found the Printer after the later user power-on,
  dark600MHz. Its retained transient BLE warnings are in the evidence; rapid
  dead-link teardown remains a separate optimization. The agent repair adds no
  idle polling, dependency or public contract changes; native artifacts stay a8b637c.
- [D-Bus match-rule contract](https://dbus.freedesktop.org/doc/dbus-specification.html#message-bus-routing-match-rules)
  supports exact object-path filters with `arg0path`; `arg0` only matches strings.
  The implementation also validates the exact body path and current unique sender.

## Installed acceptance

Python repair **78d771f** is pushed and installed; production agent hash matches the
independent review. One installed normal-service Bluetooth restart re-registered in
**1.082 s**, same PID17914, with 22 sampled CPU clocks all600MHz. Native artifacts
remain a8b637c. Normal services17914/17912 are active/NRestarts0, dark600MHz,
FTP220/200, no current application warnings/errors, and no temporary observer/drop-in
or GPIO mock. Printer absent at that capture; no film was used. A later real agent
authorization and film0 status succeeded in the candidate after daemon restarts;
this is separate from agent-registration timing and no rapid Printer recovery claim.
