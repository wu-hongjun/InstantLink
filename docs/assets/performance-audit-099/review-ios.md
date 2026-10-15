# Independent review — iOS download progress

Reviewer: audit agent 09, separate from implementer 10. Reviewed the final
working diff against `f5ed2c8037511483299c56c3bc71cdaef3d661cc`: SyncClient,
SyncViewModel, DownloadProgressReporter, DownloadProgressState, their tests,
project source inclusion and the audit 10 evidence.

**Result: no actionable correctness or concurrency regression found.** No
production or test files were changed during this review.

## Download and terminal behavior

`SyncClient.swift:132–185` retains the original HTTP handling, file writes,
delegate consumption/backpressure, cancellation check and checksum order.
Reporting starts only after an accepted response establishes the offset:
200 resets to zero, while 206 retains the existing partial length. Header
rejection produces no callback, so the per-attempt state initialized from
previously displayed bytes preserves the earlier count on failure. The new
denied-resume regression checks both the unchanged file and visible count.

Each count advances only after a successful chunk write. The reporter's scope
exit runs on normal completion and throwing exits; the handle closes before
the pending final count is reported. This scope ends before the existing
cancellation/checksum checks, so SyncViewModel's catch paths can read the final
delivered count synchronously. A checksum failure does not suppress final byte
delivery or bypass the existing corrupt-file removal. The complete-staging
verification path remains unchanged and directly emits its completed count.

The reporter is owned by one stream consumer, uses a monotonic clock and
retains only the latest pending scalar count. `finish()` clears that value,
preventing duplicate finish delivery. It adds no timer, retained chunk,
parallel writer or stream buffering. The unchanged 4 MiB watermark mechanism
still receives `consumed` immediately after each successful write.

## UI ordering and isolation

`SyncViewModel.swift:273–330` creates one delivery state for each attempt.
Synchronous callbacks update that state before queuing MainActor work. Tasks
read the current count when executed, so reordered queued tasks cannot replay
older captured counts. Invalidation and the transfer-state guard prevent old
callbacks from overwriting retries or saving/done/failed states. The active
check and transfer mutation have no MainActor suspension point between them;
invalidation on completion or forgetting the Bridge also runs on MainActor.

Successful download explicitly sets the full count before saving, and error
paths read the latest scalar count before invalidating the attempt. The
existing `isSyncing` guard and sequential item loop prevent overlapping
attempts. `forgetBridge()` invalidates the current delivery state before clearing
transfers. Weak capture of the view model avoids a new callback ownership cycle.

DownloadProgressState is Sendable through a private immutable
OSAllocatedUnfairLock reference; its mutable payload is only Int64/Bool state.
No network, disk, Photos operation, user callback or MainActor hop occurs while
the lock is held. The reporter itself is not shared between tasks.

The download → checksum → Photos save → acknowledgment → mark-synced sequence
is unchanged. The progress code neither acknowledges early nor alters pairing
credentials, staging paths, checksum policy or the existing cancellation scope.

## Evidence and limits

Reviewed the 51-test simulator result: zero failures and one existing Keychain
environment skip. Tests cover reporter timing/flush boundaries, cancellation
unwind, initial/terminal counts, latest-value state, invalidation, denied resume,
accepted 206/200 behavior and existing completed-staging/checksum cases. The
actor-delivery reasoning above supplements helper-state tests; this review did
not run an additional live UI scheduling or injected midstream network-failure
test. The XcodeGen source directories include both new service/test files.

The benchmark measures callback counts using deterministic arrival timestamps
and actual production reporter code. It includes the new initial callback and
final flush; the reported extra callback for slow streams is accounted for.
The report correctly limits its claim to reduced UI task submissions and
documents that a suppressed update during a stalled stream waits for the next
chunk or terminal event. It does not establish network, Photos or energy gains.

No additional compilation, heavy test, hardware operation or Git mutation was
performed. No physical iPhone/Bridge, real Photos-library save or iOS 17 host
validation was performed by this reviewer. Unchanged lifecycle behavior outside
the progress optimization was not expanded into unrelated findings.
