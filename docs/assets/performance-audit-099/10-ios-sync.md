# iOS sync progress delivery

## Audit and change

The iOS client already writes URLSession chunks directly to disk with 4 MiB
backpressure and verifies the completed file with a streaming SHA-256 pass.
PairingStore already caches synced IDs. The bounded opportunity was progress:
each downloaded chunk invoked a callback that scheduled a MainActor task,
searched the transfer array, and published a SwiftUI change.

`DownloadProgressReporter` now reports the accepted response's starting offset,
then intermediate counts at intervals of at least 100 ms. A scope exit flush
reports the last successfully written count, including when the stream fails
or cancellation ends it. Checksum verification remains over the completed disk
file. Resume, backpressure, request authentication, Photos save before ack, and
persisted sync state retain their existing code paths.

The view model uses one `DownloadProgressState` per attempt. Queued UI tasks
read its latest count and ignore invalidated attempts and transfers outside
the downloading state. Success sets the exact byte count before entering
saving; failure and cancellation synchronously read the latest count. A retry
preserves previously displayed bytes until an accepted response reports either
the resumed offset or zero for a full restart. Forgetting the Bridge invalidates
the current delivery state.

## Measurement

Run from the repository root on macOS:

```sh
python3 docs/assets/performance-audit-099/10-ios-progress-benchmark.py
```

The runner acquires `/tmp/instantlink-099-benchmark.lock`, compiles the actual
production reporter using `xcrun swiftc -O`, and replays 1,600 chunks of 64 KiB
(100 MiB) with deterministic monotonic timestamps. The original implementation
called progress once per chunk; the measured optimized counts include the new
starting-offset callback and final flush. Compilation is outside the measured
operation; the metric is callback count, with no wall-clock speed claim.

| Simulated chunk spacing | Original callbacks | Optimized callbacks | Change |
| --- | ---: | ---: | ---: |
| 1 ms | 1,600 | 17 | 98.94% fewer |
| 10 ms | 1,600 | 161 | 89.94% fewer |
| 200 ms | 1,600 | 1,601 | One extra starting-offset callback |

Every emitted progress callback schedules one UI task, so the fast traces
also eliminate 1,583 and 1,439 MainActor task submissions respectively. These
are synthetic arrival traces, not measured Bridge transfer rates. Results are
recorded in `10-ios-progress-results.json`. The benchmark checks the first
offset, monotonic output, and exact final 104,857,600-byte count.

Environment: arm64 macOS 27.0.1 (26A434), Xcode 27.0 (27A266a), Apple Swift 6.4.

## Validation and limits

Tests exercise immediate initial reporting, exact interval boundaries, terminal
flush without duplication, cancellation unwind, empty and slow streams,
retained progress before an accepted response, full restart to zero, latest
value delivery, and invalidated attempts. URLProtocol tests cover accepted
resume/restart offsets, denied resume retaining the file and visible count,
final progress on checksum failure, and all existing client contract cases.

Simulator suite command, run under the same exclusive build lock:

```sh
cd ios
xcodegen generate
xcodebuild test -project InstantLink-iOS.xcodeproj -scheme InstantLink-iOS \
  -destination 'platform=iOS Simulator,id=657CB222-AE66-4F0E-9783-431CE286072C' \
  CODE_SIGNING_ALLOWED=NO
```

The selected simulator is iPhone 17 running iOS 27. No physical Bridge,
Printer, camera, or iPhone smoke test was performed. Physical Wi-Fi throughput,
Photos latency, end-to-end sync time, energy, and allocations were not measured.
The policy adds one monotonic clock read per received chunk. It uses no timer:
when a network stream stalls after a suppressed update, that final partial
count becomes visible at the next chunk or terminal event. Continuous streams
publish at approximately 10 Hz, subject to chunk timing and MainActor load;
slow streams publish every chunk. This changes progress cadence, not layout.

Final result: **51 tests, zero failures, one skip** (`TEST SUCCEEDED`). The
existing PairingStore save/load round-trip test skipped because Keychain was
unavailable in the simulator test environment. `git diff --check -- ios` also
passed, as did Ruff lint and formatting checks on the Python benchmark runner
using the Bridge configuration. A test-log excerpt is recorded in
`10-ios-validation.txt`; the full local log is
`/tmp/instantlink-099-ios-tests.log`. AppIntents metadata extraction produced an informational
warning that the iOS app has no AppIntents framework dependency.

Self-review specifically checked retry offset preservation, accepted 200
restart, delayed task ordering, terminal flush before checksum, invalidation
on forget/completion, and no new stream buffering or timer lifetime. The
attempt's lock holds only scalar state; disk/network/Photos operations never
run while it is held. The baseline's per-callback transfer-array lookup remains,
but is invoked much less often for fast chunk streams.
