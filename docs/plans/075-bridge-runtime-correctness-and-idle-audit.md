# Bridge runtime correctness and idle audit

## Scope and evidence

The user prioritizes system correctness and efficiency over battery-runtime benchmarking.
The Pi is disconnected for other work. Audit the saved runtime journals, status/recovery
records and source locally; do not claim access to the complete current Pi journal or deploy
without a reachable device. Source baseline: clean `20a6eb0`, native `f574445`.

Saved evidence covers boot, normal connected/offline polling, Wi-Fi recovery, FTP/printing,
and the recent extended idle/power-on cycle. Several captures are filtered or overlap, and
older captures precede subsequent fixes. Distinguish observed events from source-derived
findings. Personal photo data and raw journals remain outside Git.

## Findings and implementation

1. A failing blocking FFI worker can replace its caller's cancellation during the cleanup
   grace period. A completed worker raising TimeoutError can also be mistaken for a stuck
   worker. Preserve cancellation after consuming the completed worker's error, retain
   serialization until actual completion and keep the existing deadline for genuinely stuck
   workers.
   The print sender watchdog has the same TimeoutError ambiguity: inspect completed results
   before reporting a slow or stuck print, preserving a sender's own timeout as a failure.
2. Obsolete Printer polls can apply failure/recovery side effects despite their generation
   being superseded. Bond-reset cancellation is swallowed, and cancelled poll tasks are
   dropped from shutdown ownership. Reject stale results before side effects, propagate
   cancellation and retain retired task references until cleanup.
3. Unchanged status is logged at INFO on every poll; ordinary Printer absence produces
   repeated warnings and scan progress. Keep state changes/recovery and genuine errors
   visible, move unchanged observations/expected repeated absence to DEBUG, preserving
   scan frequency, status I/O, freshness and Printer recovery policy.
   Keep first/value-change/recovery status records and a five-minute healthy heartbeat at
   INFO so quiescent operation remains observable. First expected absence is INFO; recurring
   not-found scans are DEBUG. Late-stage connection failures remain visible with their stage.
4. The render maintenance timer wakes every 0.35 seconds even with the screen off. About
   collection can also continue while its page is hidden by the lock. Use a slower dark
   maintenance cadence bounded by freshness deadlines, reschedule on display transitions,
   and avoid starting hidden About collectors. Awake interaction and networking remain
   operational.

## Validation and limits

Reproduce the cancellation, stale-result and hidden-collector cases before fixing them.
Use controlled worker/events, cancelled recovery tasks and fake clocks to verify ordering,
cleanup ownership, genuine error visibility, TTL expiry and prompt wake. Run touched-file
formatting, Ruff, strict mypy, the complete Bridge suite and strict docs. Audit affected
shutdown/printing/network paths for regressions.

No native ABI, image bytes, Bluetooth pacing, config/schema, sync API, App or iOS change is
planned. Do not infer energy savings or hardware performance from timer/log reductions.
Hardware smoke and the complete live journal audit remain unavailable while disconnected.

## Audit coverage and results

Reviewed available boot journals, runtime status/recovery captures, FTP/print traces and the
prior hardware audits alongside current startup, printing, FFI serialization, UI polling,
shutdown ownership, power scheduling, image-worker/cache, FTP spool and manager-listener code.
The saved log inventory summarizes event counts and ranges without committing raw journals.
It contains overlapping and filtered sources; aggregate counts are not a complete uptime or
error-rate measurement. Several older warnings describe behavior fixed in earlier plans.

The startup branches already overlap independent CPU helper, FTP, UI and Bluetooth work.
Network callers share bounded probes and recovery backoff. Image preparation stays off the
event loop with source/cache ownership retained through cancellation. FTP upload ownership
and manager listener retry/cleanup remain intact. The main queue's bounded wait also checks
FTP listener failure; it was not lengthened at the expense of shutdown/failure detection.
Existing bond reset and silent-link recovery policy was retained because it has verified
hardware purpose; this audit fixes obsolete/cancelled callers, not Printer protocol policy.

An offline replay of the 25 saved unchanged healthy status records produced **1 INFO / 24
DEBUG** records while still making **25 fetches** and preserving readiness. This is a mocked
I/O replay, not a hardware or energy benchmark. Dark maintenance's nominal maximum interval
changes from 0.35 to 5 seconds; expiry deadlines and user wake still take precedence.

Eighteen new regression cases cover worker failures during cancellation (including its own
TimeoutError), sender timeouts before/after the slow notice, stale failure generations before
and during fetch, bond-reset cancellation, retired cleanup ownership, TTL expiry while dark,
prompt wake, hidden About reads, unchanged/changed status, sparse heartbeat and genuine error
visibility/stage tracking. Focused checks passed; the complete Bridge suite passed **1,542**
tests. Ruff, strict mypy (65 source files), touched formatting and strict docs are the final
gates. Validation host: macOS / Python3.13.9, mock I/O; no Pi or Printer accessed in this audit.

The candidate is committed/pushed for review. It is **not deployed** while the Pi is
disconnected. Installed native `f574445` and its firmware runtime are unchanged. On a future
connection, verify real lock/wake, Print/Sync transitions, cancellation/reconnect and a full
runtime journal before claiming hardware efficiency or complete live-log acceptance.
