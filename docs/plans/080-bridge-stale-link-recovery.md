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

## Pi acceptance and deployment

Clean source/native **d8cee35** installed through the normal deployment script.
FFI SHA256 `b67842fed5ce50b8b9389acdf7f55c5d2a7ad8859f30d5ec460307260dcbb06a`;
CLI `1d549bc46df1c5819abb24a1f28d830f4b8d7b05929eb55a2adb37228c07c068`.
Both manifests are clean and installed Python hashes match independent review.

- Baseline and candidate each passed eleven kernel-mockup-to-UI cases on the actual LCD/CPU,
  including nonblank wake, same-button triple unlock and ten-second abandonment. Physical
  button contacts were not actuated.
- Three20s dark600MHz offline samples per version averaged **2.550%→2.600%** of one core,
  with zero childCPU. This is unchanged within the observed variation; no idle/energy claim.
  Real startup-offline attempt periods remained approximately30s; no prompt retry burst.
- Paused-clock native tests prove one-second detection for confirmed missing-ACK disconnect,
  versus the unchanged ten-second deadline for live/unknown state. Controller fake-clock tests
  show two250ms gaps then30s cadence. These are controlled timing assertions, not live Printer
  or end-to-end performance measurements.
- During the initial session, the Printer was absent. Baseline readiness timed out after100s
  without issuing a disconnect. Subsequent power-on completed the live checks below; the initial
  failed attempt remains in evidence.
- Reviewed3226current-boot Bridge/manager journal records. Normal installed PID20395 has no
  app warnings/errors; historical079faults remain. Temporary observer had a wrong method name
  and restarted eight times; corrected before candidate tests. An early UI socket check and
  an awake44s health capture were also retried; all retained in evidence.
- Final normal services20395/20393 active/NRestarts0;600MHz/powersave/GPIO24low,42.932°C,
  throttle0x0,hotspot/USB up,FTP220/200,caches0,GPIOv2 and pairingagent registered. FTP probe
  used the Pi hotspot address and measures server health, not wireless airtime/upload.
- Owned observer/drop-in/socket/source/library and ARM test executables removed; mockup
  unloaded. Saved photos/configuration unchanged. Raw journals private0600. No film used.

Evidence: `docs/assets/bridge-audit-080/`. The following power-on session completed the
remaining live validation without production changes.

## Live acceptance after Printer power-on

The normal installed runtime automatically reconnected and reported Square film 0 / battery 20%
at 08:18:20 EDT on 2026-10-13. No manual Reconnect action was used.

- Two external Device1 disconnects recovered automatically, observed by **19.867 s** and
  **11.610 s** on the installed firmware. Every sampled state stayed locked at 600 MHz, with
  camera receive readiness preserved and fresh film 0 status after recovery. Harness times
  include state reply and a final BlueZ query; status timestamps were 19.780 / 11.561 s.
- Historical source 4c9e28b was archived and rebuilt with the same toolchain/flags. Its FFI
  SHA256 exactly matches the previously installed baseline (fdd47e…5973). Full-runtime baseline
  missed its 100 s deadline, then recovered in the same PID at **104.242 s**. All timed rows and
  the subsequent state are retained. Different poll phases and target visibility prevent a
  universal speedup claim; the target matched on a later attempt, with cause unproven.
- Baseline reused the dead cache twice, then started fresh connection attempts at 39.235,
  69.237 and 99.240 s. Installed fresh attempts started at 9.849 and 9.390 s; the first run
  needed one prompt retry after a five-second miss. This verifies the cache/retry changes.
- Direct native tests: the first status won the disconnect race on both builds (~89 ms).
  The next failed status took 2.793 ms baseline / 6.035 ms installed; baseline still returned
  connectivity 1, while installed returned 0. These show correct retirement, not reduced write
  latency or a hardware measurement of the one-second missing-ACK probe. Successful direct
  status reads all showed film 0 / history 68. Keepalive was disabled only in these test processes.
- Initial baseline direct setup missed a scan; retried setup missed another then connected.
  All failures are retained. No radio cause or baseline connection defect is inferred.
- Independent evidence review passed after correcting stale pending conclusions and timing
  labels. No additional source correctness issue; no image/print commands or film used.
- Normal service restored: Bridge PID 23036 / manager 20393, active / NRestarts 0, 600 MHz,
  GPIO24 low, temperature 42.932°C, throttle 0x0, hotspot/USB/FTP healthy, Printer connected
  with fresh Square status. Reviewed 3697 current-boot service records; normal PID has
  39 records and no warnings/errors at capture. Controlled baseline warnings and earlier
  harness/historical faults remain in the full journal; raw logs are private.
- Observer/drop-in/socket, baseline source/library and test scripts removed; configuration
  and saved photos unchanged. Current native artifacts/clean manifest restored after the
  historical rebuild; installed hashes remain the reviewed d8cee35 binaries.

The next latency candidate is the **9.4–9.8 s wait for the next status poll** after a drop.
A disconnect event on the existing shared BlueZ bus could prompt the next check sooner,
without increasing idle polling. Successful fresh connect/status attempts took 2.17–3.83 s
in these runs; these are entire attempt durations, not BLE-only timings.


### Final normal-service power-return check

After the clean 08:33 capture, the Printer stopped advertising at 08:37:01 EDT.
The cause was not observed. Two one-time status-loss warnings were logged; the same
Bridge PID 23036 retired the link, removed the disconnected bond and resumed search.
Hotspot/USB/FTP and 600 MHz operation remained healthy. A later camera FTP control
session is separate from this benchmark; no upload/airtime claim.

The user turned the Printer on again. Automatic discovery matched it at 08:43:08.842,
and fresh Square film 0 / battery 20% status returned at **08:43:12.386 EDT**, with
**no manual Reconnect action or service restart**. Power-on time was not measured.
Final health confirms the same PID / NRestarts 0, connected, 600 MHz, reviewed native
hash and clean runtime source 79b53e9. The two earlier warnings remain in the final
snapshot; there is no additional fault on power-return. No film used.
