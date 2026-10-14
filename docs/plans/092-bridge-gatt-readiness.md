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
