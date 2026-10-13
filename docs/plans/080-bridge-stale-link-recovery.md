# Bridge stale-link detection and reconnect retries

## Evidence and goal

Plan079 exposed slow cached-link recovery: a forced disconnect exceeded a
65-second test deadline before eventual recovery. Status and background keepalive
share a command lock, failed commands wait up to ten seconds, and a second failure
can fall back to the ordinary offline search period. The pairing-agent registration
defect identified there is already repaired.

Reduce wasted waits after a dead link, preserve transient-error tolerance and
bounded scan/bond recovery, and use no film in hardware benchmarks.

## Implementation boundaries

- Probe authoritative transport connectivity only while an expected response has
  been missing for a second. Bound each query; inconclusive errors retain the
  original response deadline. Idle and normally acknowledged commands add no probes.
- Confirmed disconnect closes the old transport and quickly fails queued work.
  Available acknowledgements take priority. Never replay image or execute commands.
- Keep the FFI connectivity getter cheap and callback-safe; report terminal
  disconnected state without a blocking hardware query or a new export.
- Cached Bridge sessions marked disconnected are discarded. Unknown status failures
  retain existing tolerance. Permit two short status-recovery retries after an
  online-to-failed transition, then return to ordinary offline cadence.
- Wait for both bond reset and silent-link recovery before a new status fetch;
  retain cancellation, generation guards and live-connection protection.

No image, fragment, pacing, settings, CPU tier or sync-contract change.

## Validation

- Independent core and Bridge implementation, plus adversarial review.
- Mocked timing, ACK/disconnect races, inconclusive queries, cancellation, queued
  work, keepalive ownership, bounded retry and recovery/fetch concurrency tests.
- No-film baseline/candidate native status latency and full-runtime reconnect,
  with all failed attempts retained and radio absence distinguished from timing.
- Affected local gates, actual ARM64 unit execution, clean source/native manifests,
  deployment, final log/health checks and removal of owned test resources.

Hardware: Raspberry Pi Zero 2 W Rev1.0, ST7789 LCD and X306; Instax Link Square
INSTAX-52006924. Debian13.2, Linux6.12.47+rpt-rpi-v8, Python3.13.5, BlueZ5.82.

## Source acceptance

Independent review found and resolved a recovery/fetch overlap: both rebond and silent-link
cleanup are now awaited before a fresh connection. Final frozen review passed, including
ACK precedence, bounded/inconclusive queries, cancellation, callback-safe getters, scoped
keepalive ownership and bounded retry budget. Sixteen independently selected cases passed.

Host locked workspace tests: 291 unit/integration plus one doctest; App 156; Bridge 1689.
Pi ARM core 190 and FFI 39 passed. Linux production Clippy is strict; test-target Clippy
retains four existing test-only lint allowances (new_ret_no_self, items_after_test_module,
type_complexity and unnecessary_cast). Host Clippy, formatting, header drift, Ruff, strict
mypy (67 files), touched Python formatting and strict docs passed. Native ARM testing found
an existing signed-c_char test buffer portability error; the test now uses c_char.

Hardware acceptance and final deployment evidence will follow below. No film is used.
