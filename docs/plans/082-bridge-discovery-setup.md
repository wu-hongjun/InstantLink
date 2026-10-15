# Bridge discovery and connection setup

## Goal

Reduce measured discovery/setup overhead while preserving automatic reconnect, model detection,
notification readiness, selected identity and command serialization. Real-device validation
uses status requests and external disconnects only; no film or image/print commands.

## Work

- Subagents audit native setup, Bridge bond gating and dependency lifecycle independently.
- Reuse the agent bus for a fresh bounded connected-identity check with conservative CLI fallback.
- Overlap read-only MTU discovery with the existing notification-settling floor; retain fallback.
- Correct the observed bluez-async message-stream cleanup panic without suppressing other failures.
- Retain active-scan/ambiguity/Android/liveness and retry behavior. Avoid optimistic cached
  advertising assumptions or additional idle polling.

## Acceptance

Record baseline/candidate/installed setup stage timings and full recovery, misses and variable
radio availability separately. Compare negotiated MTU/payload, low-frequency locked state,
status freshness, camera/network readiness, subprocess/query overhead and current running logs.
Use focused cancellation/race/fallback tests, full path-scoped gates, independent adversarial
review and normal deployment. Remove owned temporary fixtures and restore normal service.

Hardware: Pi Zero 2 W Rev1.0 / ST7789 / X306, Debian13.2, Linux6.12.47+rpt-rpi-v8,
Python3.13.5, BlueZ5.82; Instax Link Square INSTAX-52006924.

## Log audit correction

Plan081's final normal-process WARNING/ERROR counts were accurate for those severity strings,
but missed a native Tokio panic printed directly to stderr during service discovery at09:41:09
EDT. Printer connection and status subsequently succeeded. The full-log scan here includes
`panicked`, D-Bus cleanup failures and thread messages so a zero structured-error count is not
misreported as complete fault absence. This task investigates and fixes that cleanup race.

## Implemented and reviewed

Clean source **82f60971f7465fa46492cda455edff38de2695b4** is installed under
`/opt/InstantLinkBridge`. Final FFI SHA256
`d23d3b817108b0243ab474af2970f1fd7748431c317af64b38bc4c5eb94f3d38`, CLI
`b3fcffc0c0d1a351e2cdafbdddee065393434cb1c01f56e6fa1239874e9502dc`.

- After an authenticated disconnect, serialized recovery closes the old session and runs
  the existing live-link guarded bond cleanup **before** its first fresh discovery. A live
  matching identity prevents removal. The first failed-fetch path does not duplicate cleanup;
  generation checks, print pauses, two prompt retries and periodic/offline fallback remain.
- The connected-identity gate uses the agent's bounded fresh snapshot, requiring one known
  adapter and valid device state. Unknown/malformed/unavailable data uses CLI. A successful
  inventory does not probe an absent old physical address; failed/unknown CLI state cannot
  authorize removal. Cancellation kills and reaps owned CLI children despite repeated cancel.
- Replacement polls join earlier cleanup and distinguish child cancellation from their own
  cancellation. Printing joins all three mutating recovery owners, with a six-second limit
  that aborts printing while retaining unfinished owners; resuming still waits before fetch.
- MTU metadata lookup overlaps the unchanged 200 ms notification settle floor, with a fresh
  post-settle retry for missing/default MTU and the original 1.2 s combined budget. A known
  small MTU remains safe if refresh fails. Print bytes, orientation, pacing and ABI unchanged.
- Localized `bluez-async` 0.8.2 patch retains receiver/match ownership, handles in-flight local
  dispatch, and removes one captured daemon match without panic. Cleanup is bounded best
  effort on daemon failure/prolonged dispatch/runtime absence. Licenses/provenance retained;
  Linux workspace scope and equivalent upstream style fixes keep normal host/Linux gates.

Independent adversarial review found and fixed unscoped negative snapshots, orphaned CLI
children, overlapping recovery, print handoff and post-cancel reconnect termination. It also
checked actual repeated host subprocess cancellation. Final independent affected suite:
**337 passed**. No source blocker remains.

## Hardware measurements

Evidence is retained in `docs/assets/bridge-audit-082/`, including complete attempts and limits.
Real status-only forced disconnects, no manual Reconnect, image/print commands or film:

| Runtime | Recovery observed by | Failed attempts | Final attempt discovery | BLE connect | Notification-to-model stage |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline 1 | 13.141 s | 1 | 0.511 s | 1.436 s | 0.721 s |
| Baseline 2 | 19.211 s | 2 | 0.502 s | 1.327 s | 0.714 s |
| Candidate 1 | 7.990 s | 0 | 0.507 s | 1.412 s | 0.593 s |
| Candidate 3 | 8.690 s | 1 | 0.515 s | 1.501 s | 0.541 s |
| Installed | 12.632 s | 1 | 0.453 s | 1.474 s | 0.688 s |

All accepted samples stayed locked at 600 MHz and camera-ready, in one PID per run. Baseline
losses spent a full scan before bond cleanup. Earlier cleanup removes that avoidable ordering
but does not guarantee advertisement availability: installed still had a five-second scan miss.
Candidate 3 recovered after a transient missing write characteristic using existing rebond.
Small samples, uncontrolled radio availability and observer overhead prevent a universal
speedup claim. The first status fetch now waits for guarded cleanup by design; it is not a
pure comparison with plan081's signal-to-fetch timing. Every successful payload selection
remained **MTU 247 / 236 bytes**, conservative=false. Physical print quality was not retested.

Three 20 s connected idle samples at 600 MHz: baseline 0.450/0.350/0.450% of one core
(mean **0.417%**), candidate 0.400/0.400/0.700% (mean **0.500%**), child CPU zero.
Separate runtime starts and ambient work prevent CPU/energy improvement or regression claims;
all rows are retained. No extra idle polling or per-status snapshots were added.

An early prototype was absent for its 100 s initial readiness wait. Candidate 1 has a complete
passed JSON but its stdout capture encountered ENOSPC; candidate 2 could not save JSON and is
excluded. Owned ARM test binaries filled the 232 MiB RAM-backed `/tmp`; removed them and moved
later unit executables to SD-backed `/var/tmp`. Repeated candidate 3 capture passed. This was
an audit-fixture storage fault, not an application failure. No unusable timing is inferred.

Installed abstract button input through the production controller and physical LCD/CPU passed
same-button triple unlock, nonblank wake at 1000 MHz, relock at 600 MHz, status pause/resume
and disconnect-watch rearming. Physical button contacts were not actuated; no GPIO mock used.

## Final acceptance and next bottleneck

Normal service 10:43:26 EDT: Bridge PID29062 / manager28530 active, NRestarts0, Printer connected,
600 MHz powersave, GPIO24 low, 45.084°C, throttle0x0, GPIOv2, hotspot/USB up, FTP220/200, hashes
match clean manifests. FTP probe uses the Pi's own hotspot address, not camera wireless upload.
Observer/drop-in/socket/source/library overrides and owned test binaries removed. Saved photos
and configuration unchanged. Reviewed **6642** current-boot service records, including native
stderr panic strings; final normal processes have zero warning/error/panic records. Historical
panics and controlled transient failures remain in the counts; raw journals stay private.

Gates: normal hooks **1763 Bridge tests**, 27 existing GPIO/deprecation warnings; host Rust
298 tests +1 doctest, App156, targeted337, strict mypy67, Ruff/touched format, Rustfmt,
host/Linux production strict Clippy, header drift and strict docs. Pi ARM core197, final
vendor51 +4 isolated D-Bus race tests, final FFI39 passed. Host vendor is intentionally empty
on macOS; Linux tests run on Pi with no Printer. Final release has the existing Zig linker
optimization warning; Rust production Clippy is strict. Initial host hook used a build-tools
Python lacking pytest; rerun with the Bridge venv passed without skipping hooks.

Remaining latency is advertisement availability, occasional GATT export/rebond, and roughly
1.3–1.5 s BLE connection setup. Initial native status takes 0.43–0.54 s and the Bridge then
requests status again; removing duplicate status work is a possible next change with a
carefully scoped freshness/connection contract. No further timeout/settle reduction is justified
by these samples.

Final independent hardware-evidence review also passed. All five accepted captures match
reported timing/state/counts; final normal-process logs and clean mapped artifact hashes
match. See `hardware-review.json` for the complete reporting limits.
