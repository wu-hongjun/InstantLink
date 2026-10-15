# Bluetooth GATT readiness after service restart

## Goal and boundaries

Fix uncertain GATT setup being classified as a stale bond, keep setup waits bounded, preserve
fresh status/automatic reconnect, benchmark real warm restarts and deploy without film.
Three subagents cover pinned-source audit, implementation and independent adversarial review.
Root owns all hardware mutations. No image, print, reset, LED or actuator commands.

Pi Zero2W Rev1.0/ST7789/X306, Debian13.2/Linux6.12.47+rpt-rpi-v8/Python3.13.5/BlueZ5.82;
Link Square INSTAX-52006924. Baseline clean application35d8a0c, nativeb2b6c8c/FFI9e31f998…34031.
Wi-Fi AP cleanup backport and unused-media profile from plans090/091 retained.

## Findings

Pinned btleplug0.11.8 discovers GATT by introspecting exported objects. A successful introspection
can return an incomplete table; connected state does not prove service resolution. The normal
connect path waits for BlueZ ServicesResolved, but reused-link and CLI fallback paths can skip
that wait. See the [BlueZ Device API](https://bluez.readthedocs.io/en/latest/device-api/) and
vendored bluez-async await_service_discovery.

The old characteristic loop declared a2s deadline while is_connected/rediscovery I/O remained
unbounded inside it. Link-down/state-query failures exited as missing-write-characteristic,
which Python treated as stale-key evidence after lookup. Progress retained a prior attempt's
highest phase even after a fallback restarted service discovery.

Plan091's two failures ended about0.3s after lookup, before the2s deadline, followed by bond
removal/retry and eventual normal recovery66.480s. The retained log lacks HCI reasons/raw readiness
properties, so it cannot establish why those radio links dropped. Do not claim a readiness
barrier is proven to prevent radio drops.

## Changes

Successful ordinary btleplug connect with a complete table keeps its healthy path. Reused and
CLI-assisted connections must confirm readiness even for a complete cached table. Otherwise,
on incomplete exports the native resolver reads
fresh typed Connected/ServicesResolved for the exact Linux device and uses one2s deadline for
state queries, rediscovery and waits. Unknown state retains bounded discovery fallback; pending
resolution waits. Link loss/unconfirmed readiness produces explicit transient setup detail.
Only a freshly resolved incomplete table, confirmed live again in the final poll window, retains
the missing-characteristic fingerprint. Genuine subscribe/write/authentication recovery remains.

Python carries terminal progress detail with the generic C ABI error, resets current phase on
retry regressions, and excludes anchored transient readiness/link-down errors from bond removal.
An explicit org.bluez.Error.AuthenticationFailed from rediscovery retains existing recovery.
Legacy native builds without detail keep their compatible phase heuristic. No C ABI/image/model/
transport fragment/pacing/config/sync contract changes.

Review found a Linux plumbing mistake in the initial candidate: btleplug IDs are relative,
while BlueZ object paths are absolute. Corrected through the production /org/bluez prefix wrapper
and added a Linux test through that same wrapper before build/deployment.

## Validation and baseline

Two warm observed restarts on unchanged baseline, Printer initially Connected/ServicesResolved:
restart→fresh16.314/16.268s, first status attempt→fresh3.461/3.604s; subsequent fresh polls pass.
These healthy baseline runs do not reproduce the earlier missing-characteristic failures.
Read-only BlueZ metadata/signals and identical observer used for all cohorts; no image data.
Warm restart timings include startup pairing/radio/retries and are not cold boot or energy tests.

Source tests exercise delayed export, pending/unknown/live/down state, malformed/wrong device,
blocked I/O deadlines, cancellation, genuine missing characteristics, phase regressions and
explicit authentication failures. Linux-specific execution and live candidate/installed tests
follow before final acceptance. Full running logs are retained privately; sanitized evidence
under docs/assets/bridge-audit-092.

### Additional cached-table finding

[BlueZ5.82 GATT client](https://raw.githubusercontent.com/bluez/bluez/5.82/src/gatt-client.c)
retains exported characteristic objects when its connection client is cleared; the
[device lifecycle](https://raw.githubusercontent.com/bluez/bluez/5.82/src/device.c)
resets ServicesResolved separately. A complete cache is therefore insufficient for reuse or
CLI-assisted connections. The provisional b2e4e2a candidate was installed while the Printer
was off; it was not accepted as the final live fix. Independent review identified this case
before live acceptance. The corrected evidence policy tracks successful btleplug connect
versus reuse/assistance and updates after internal reconnect. Unknown or pending state cannot
accept cached characteristics on guarded paths. Fifteen independent Mac GATT tests now pass.

Full first-stage Linux core tests227passed on the Pi, including11GATT tests, before this additional
guard. Full normal host checks2383Bridge tests/27existingwarnings, Rustworkspacefmt/clippy/tests,
Ruff/strictmypy67 and FFIheaderdrift passed. One unchanged HIF descendant-timeout fixture failed
under concurrent compilation; four affected cases then full normal gate passed unchanged.
Corrected Linux guarded-path execution and live comparisons follow; no film used.

## Live acceptance

| Matched warm restart | Baseline (two runs) | Corrected candidate (two runs) |
| --- | --- | --- |
| Dispatch→fresh status |16.314/16.268s (median16.291)|16.127/16.215s (median16.171)|
| First status attempt→fresh |3.461/3.604s (median3.532)|3.556/3.523s (median3.540)|

Both cohorts started Connected/ServicesResolved and completed a subsequent fresh periodic poll.
These small healthy samples show no established speedup and do not reproduce the earlier
intermittent failure. Timings under the observer cannot be compared directly with normal service.
Final Linux16GATT tests passed on the Pi, including complete-cache guard and deadline/cancellation;
corrected host212core tests and full workspace gates passed. Native/source hashes match clean
6d61384; FFIb91cf3fd…ea1175, CLI f1d325ac…31b21f.

Status-only external Disconnect recovered automatically in **7.191s**, all16samples locked600MHz/
samePID5266/camera-ready; invalid timestamps marked stale, fresh status restored watch1/retired0.
Same-button triple unlock/exact nonblank LCD1000MHz, relock600,10s abandonment and status
pause/resume/watch rearm passed. Physical switch contacts not actuated. Film0 unchanged.

Normal service without observer restarted successfully: dispatch→observed fresh7.204s and
boot-start marker→fresh4.811s, no warning/error records. Final PID5618/manager637 active with
zero automatic restarts, connected50% LinkSquare,600MHz powersave/FTP220+200/GPIOv2/no fallback,
throttle0x0. No cold-boot, physical-camera upload, battery or transport-speedup claim.

Full available boot journals945service/378kernel records: six historical service flags belong
to earlier manager/PID2626 scopes; no candidate/normal flags. Ten expected hardware/staging/
backport notices remain, zero VCHI/media-null unregister and Wi-Fi vendor-IE errors. Raw journals
private; independent source, Linux and live evidence reviews passed.

Final review preserves canonical native org.bluez.Error.AuthenticationFailed recovery even at
connect-stage3: actual authentication can fail before lookup under the readiness barrier. Generic
early BLE errors, near-match error names and generic Python exception text do not authorize
rebond. This final classifier refinement changes no native/image/healthy-connect path.

### Final classifier deployment

Clean59ef504 installed after the full2388Bridge tests/27existingwarnings, Ruff/strictmypy67 and
independent66focused tests. Native6d61384 artifacts remain unchanged. Normal service restarted
with latest classifier, healthy FTP220/200/GPIOv2/no fallback,600MHz powersave,0automatic restarts
and no current application warning/error records. Printer was offline after its idle shutoff;
final power-on request remained unanswered at capture. The connected live comparisons above
used6d61384 before this pure failure-classification refinement. Updated early-auth behavior is
covered by native-progress/provider tests; no pairing-key corruption was forced on hardware.
Post-refinement live connected confirmation remains pending Printer power-on. No film used.

### Post-refinement connected confirmation

The user powered the Printer on again. Installed runtime `1f9dda2` (classifier `59ef504`, native
`6d61384`) reached fresh film-count status with no setup warnings: restart dispatch to observed
fresh status took 18.552 seconds; application boot-start marker to fresh status took 5.523 seconds.
The dispatch interval includes stopping the
previous runtime; it is not directly comparable with the earlier boot-marker metric.
No film was used and no image or actuator commands were sent.

Final normal runtime PID 6758 and manager PID 637 were connected with fresh status at 600 MHz,
backlight GPIO 24 low, 45.622°C and throttle flags `0x0`. FTP returned 220/200, GPIO v2 was active,
and both services had zero automatic restarts. External BlueZ Disconnect dispatch to fresh status
took **12.171 seconds**; all 22 probes retained 600 MHz, powersave, backlight low, the same PID
and FTP 220/200. The native disconnect event was recorded, with no warning/error messages.
Internal lock/watch flags were not
introspected in this normal-service check; their prior observer validation remains separate.
This confirms final classifier deployment; the previously pending power-on acceptance is complete.
No pairing-key corruption was forced. Read-only FTP probes used the same-Pi address.
The independent [confirmation review](../assets/bridge-audit-092/confirmation-review.json) passed
with no outstanding findings or pending acceptance checks.
