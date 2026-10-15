# Bridge initial disconnect-watch registration

## Goal

Reduce work needed to arm the initial Bluetooth disconnect watch while preserving automatic
reconnect, fresh status and ownership during pause, printing, selection changes and shutdown.
Hardware benchmarks use status requests and external disconnects only, with no film.

## Approach and acceptance

Reuse a complete Device1 identity snapshot maintained by authenticated BlueZ signals, scoped
to the current bus, owner, generation and lifecycle. Fast arming requires an unambiguous live
Printer identity; incomplete, invalidated or ambiguous state retains the bounded fresh-snapshot
fallback. Signals received during snapshot resolution must win over older replies. Keep owned
cleanup, bounded state and the periodic status fallback. Controller completion must still own
its registration token and selected Printer identity before retaining the watch.

Subagents implement the agent and controller boundaries, with independent adversarial review
of race, malformed-input, sender/identity, lifecycle and cancellation cases. Measure actual
watch duration and snapshot calls separately from UI rendering and status completion. Compare
baseline/candidate/installed startup and locked reconnect, preserve failures/radio variation,
run path-scoped gates, deploy clean source and restore normal service/remove owned fixtures.

Hardware: Pi Zero2W Rev1.0/ST7789/X306; Debian13.2/Linux6.12.47+rpt-rpi-v8/Python3.13.5/BlueZ5.82;
Instax Link Square INSTAX-52006924. No image/print commands or physical film-quality retest.

## Source acceptance

Clean **57e7db9** implements the bounded identity cache and registration ownership checks.
Existing fresh GetManagedObjects calls seed Name/Alias/Connected identity fields. Authenticated
signals maintain them, scoped to the agent lifecycle, bus and BlueZ owner. Fast arming requires
one unique matching connected identity and a live shared bus. Missing, ambiguous, malformed,
invalidated or disconnected-bus state retains the fresh bounded snapshot fallback. The cache
is capped at 512 rows and adds no startup query/task or per-poll work. The bond-removal gate
continues to read fresh state. Signal revisions prevent older replies restoring removed or
changed identities. Stop and owner transitions clear reusable state.

Controller completion checks its registration token, current generation and selected address/
name before retaining the unsubscribe callback. A delayed obsolete result cannot replace a
new watch. Source and independent tests cover snapshot/removal/readdition races, stale/spoofed
senders, malformed/invalidation input, bus/owner/lifecycle changes, ambiguity, cancellation,
stop, pause, print handoff, selection and newer same-generation ownership.

Normal hooks passed **1807 Bridge tests**, 27 existing warnings, Ruff, strict mypy (67 modules) and touched
formatting. Strict MkDocs passed. Producer agent/pairing (122 tests) and controller (270 tests) passed;
independent affected suite (392 tests) plus 3 additional adversarial cases passed. No C ABI, native,
config or sync schema changes. Native source b2b6c8c remains installed, FFI SHA256
`9e31f99896ece2b687652bfdd0e80318a349cdb387c4e8c2d44ef35fa0d34031`.

## Hardware acceptance

Watch registration is timed directly, with same-task snapshot spans attributed within each
call. These are small samples on the hardware above, not estimates of whole boot or energy.

| Registration | Duration | Extra snapshot reads |
| --- | ---: | ---: |
| Baseline startup1 | 10.984ms | 1 |
| Baseline startup2 | 13.524ms | 1 |
| Candidate startup | 0.495ms | 0 |
| Installed startup | 0.484ms | 0 |
| Baseline reconnect | 31.172ms | 1 |
| Candidate reconnect | 0.792ms | 0 |
| Installed reconnect, cache inconclusive | 26.486ms | 1 |
| Installed pause/resume | 0.541ms | 0 |
| Installed audit-only forced fallback | 10.061ms | 1 |

The initial fast path removes one snapshot and about 10–13ms from the measured registration.
Natural installed reconnect used the safe fallback; zero-request registration is conditional.
The audit-only fallback invalidated identity state, armed a temporary second watch, then
unsubscribed immediately, leaving the production watch intact. Startup had one existing bond
snapshot versus baseline two total reads. Later status requests still sent fresh selectors 1/2/3.
All captured wire commands were status/model queries; **no image/print commands or film used**.

External-disconnect recovery took 11.824s baseline, 7.179s candidate and 12.588s installed.
Baseline/installed each had a failed first scan before automatic recovery. All 32/15/35 accepted
observations respectively remained locked, not unlocking, 600 MHz and camera-ready. Radio and
scan variation prevent attributing full recovery differences to this millisecond optimization.
Correct physical FA:AB:BC:C7:95:64 watch, fresh periodic polls, same-button triple unlock/nonblank
LCD at 1000 MHz, relock at 600 MHz and status pause/resume passed. Abstract input used production
controller/physical LCD; button contacts were not actuated. Physical print quality not retested;
native image/printing code and artifacts are unchanged.

### Correction of prior timing attribution

The earlier plans/context attributed the roughly 223ms Connected→status-fetch-return tail to
watch registration. The watch starts **after** fetch returns, so that attribution was incorrect.
Candidate direct render instrumentation measured the NoFilm LCD render at 219.344ms inside
that fetch. Historical measurements remain valid, but that tail measures rendering/status
publication rather than watch setup. Visible LCD rendering is the larger remaining local cost.

The existing Plan084 model-query retry was incidentally exercised on hardware: candidate sent
one capability query, received no reply during its first window, and resent 1.002s later. A
matching reply arrived 186ms after resend (1.189s after first write), then fresh status completed
on the same connection. Identical writes prevent assigning that reply to a particular request;
this validates the live retry path without claiming the resend caused the response.

Clean Python 57e7db9 deployed; native unchanged. All observed task 085 service processes had zero
matched warning/error/panic messages, including safe scan-miss recovery. Final normal service
at **19:33:33 EDT**: PID36582/manager36128 active/NRestarts0, Printer connected, 600 MHz powersave,
41.856°C/throttle0x0/GPIO24low/GPIOv2/hotspot/USB/FTP220/200 healthy; source/native hashes match
clean manifests and the loaded production library. FTP probe uses the Pi's own hotspot address,
not a wireless upload. Full current-boot Bridge/manager review covered 10681 records, retaining
134 historical matched messages including two earlier native panic episodes. No kernel-log
claim. Observer/drop-in/socket/candidate archive/source and final health script removed.

Independent source, hardware and final health/log adversarial review passed. Evidence under
`docs/assets/bridge-audit-085/`; raw journals remain private. Next measured local cost is visible
LCD rendering (~220ms per changed frame); advertisement/GATT availability and BLE handshake
also remain variable setup costs. Periodic status and safe fallback stay enabled.
