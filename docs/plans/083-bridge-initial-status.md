# Bridge initial status handoff

## Goal

Remove the duplicate Printer status read after a named progress connect. Keep status freshly
read during each caller request, automatic reconnect and cancellation ownership. No retained
status cache or time-to-live policy. Hardware checks use status/disconnect only, no film.

## Design and validation

Subagents implement core/FFI and Bridge integration; independent adversarial review checks
initial failures, unchanged connected polling, status identity, callback/pointer safety,
replacement/cancellation and older-library compatibility. An additive connect-and-status
FFI returns the successful initial read directly. Existing API meanings remain unchanged.

Compare baseline/candidate/installed status command count and setup/status-tail times,
keeping failed attempts, scan/radio variance, locked600MHz/camera-ready state and full
running-log review. Validate all path-scoped gates, deploy clean native/Python artifacts,
restore normal service and remove owned fixtures. Pi unit binaries use SD-backed /var/tmp.

Hardware: PiZero2WRev1.0/ST7789/X306, Debian13.2/Linux6.12.47+rpt-rpi-v8/Python3.13.5/BlueZ5.82;
InstaxLinkSquare INSTAX-52006924.

## Source acceptance, 2026-10-13

Clean source **ffe637e** implements the additive seven-argument C entry point with four signed
i32 status outputs. A fresh request consumes the connection's initial read once; established
polls and the existing print connection path retain their hardware reads. Older libraries
retain their established fallback; a new-API failure does not retry another connect entry point.
No cache or TTL is introduced. Non-connect operations retain the existing caller serialization
contract. Null inputs preserve outputs/current session, and failed initial reads retire the
provisional connection without publishing status.

Independent adversarial review fixed two lifecycle issues: ordinary disconnect retains
admission through physical teardown, and caught panic cannot poison the unit admission guard
permanently. Callback disconnect invalidates provisional generation; reentrant connect fails
promptly rather than deadlocking. A further freshness fix moves successful scan cleanup before
the initial status read, with no awaited adapter cleanup after successful sampling. A gated
regression changes replies during cleanup and verifies the new values, using one status sequence.

Normal hooks passed **1773 Bridge tests**, 27 existing warnings; **308 Rust tests +1 doctest**,
App156, Ruff/strict mypy67, formatting, production Clippy, header generation/drift and strictdocs.
Independent suites: Bridge55, FFI23, corePrinter23 and cleanup regression1. Pi ARM connect tests23
plus teardown/panic checks2 passed with no Printer. Source review/hashes are retained under
`docs/assets/bridge-audit-083/`. Final Linux FFI SHA256
`88974b10dd285f4eb3b31a08fc8af68756d3612e5cdf8910a1c719b74e265e82`; CLI
`e720bef273ebfca85b96743d85b9c77bb99dd8fcce13fc91e9d3ba52b15f7d79`.

### Earlier checkpoint before Printer power-on

Live benchmark and task083 deployment were **pending**: the selected Printer was not advertising
and the power-on request has not been answered. No radio timing or real successful command count
is claimed. The previous validated Plan082 firmware remains installed. The baseline observer,
drop-in/socket and owned ARM unit executable were removed; normal service restored. Prepared
candidate source archive/library remain inactive under SD-backed /var/tmp for the live follow-up.
No image/print commands or film used.

## Live acceptance and deployment, 2026-10-13

After Printer power-on, baseline/candidate/installed tests completed on the hardware above.
No image or print commands, and **no film used**. Clean Python source **83473d4** and native
source **ffe637e** installed; native hashes match source acceptance. The Python differences
between those commits are documentation only.

| Measurement | Baseline | Candidate | Installed |
| --- | ---: | ---: | ---: |
| Successful fresh-connect status commands | 6 | 3 | 3 |
| Connected stage to completed reconnect status | 514.530 ms | 3.515 ms | 5.448 ms |
| Observed external-disconnect recovery | 12.706 s | 7.069 s | 6.918 s |
| Subsequent periodic status commands | 3 | 3 | 3 |

Each status sequence is battery, film/charging and history. The returned fields are from the
same successful physical connection; later polls read hardware again. Candidate and installed
captures include successful subsequent periodic requests after reconnect. The roughly **0.51 s**
removed from the measured reconnect tail is supported by packet counts. Startup tails remain
about223ms, including first-watch registration; do not interpret these results as eliminating
all post-connect work. One measured disconnect per variant; scan and radio variation prevent a
universal full-recovery speedup claim. Baseline had an additional5.13s unsuccessful scan.

Baseline and candidate each had a startup model-response timeout and recovered automatically;
those failed attempts remain in the evidence. The first harness launch preceded socket readiness
and failed without touching the Printer; it was rerun after service startup. Installed observer
log had zero warning/error/panic messages. All35/15/16 accepted recovery observations respectively
were locked, not unlocking,600MHz and camera-ready. MTU247/payload236 retained.

Installed same-button triple unlock produced1→2→unlocked, nonblank LCD at1000MHz; relock returned
to600MHz. Status pause retired the watch, and resume restored a fresh status/watch. Inputs used
the production abstract GPIO actions and physical LCD; button contacts were not actuated.
Independent adversarial review checked raw packet counts, later freshness, failures, lock/clock
samples and UI behavior and found no remaining acceptance blocker. Physical print quality was
not retested because this task uses no film and changes no image bytes.

Evidence: `docs/assets/bridge-audit-083/live-benchmark.json` and `installed-ui-smoke.json`.
Raw journals remain private under host /tmp. Audit observer/drop-in/socket and candidate
source/library/archive were removed; normal service restored before final health verification.
Remaining setup costs include variable advertisement/GATT availability, the BLE handshake,
model-query timeout recovery and initial watch registration. Further optimization should
measure these boundaries without weakening status freshness or reconnect ownership.

Final normal service at **18:15:40 EDT**: PID31925/manager31549 active, NRestarts0,
Printer connected,600MHz powersave/GPIO24low,45.084°C, throttle0x0, GPIOv2,
hotspot/USB and FTP220/200 healthy. Native/Python hashes match deployment manifests, dirty=false.
Normal startup repeated the baseline model-query timeout (two warning lines), then recovered
and reported fresh100%/not charging/film0 at18:15:06. This log is not described as warning-free.
Full current-boot Bridge/manager review covered8078 records, retaining
132 matched warning/error/panic messages and two earlier native
panic episodes (four matching lines, PIDs24547/25926). Installed observer had zero matched
issues, and no task083 native panic. See final-health.json, cleanup.json and running-log-review.json.
One early final-health probe ran before the60s auto-idle boundary and correctly saw1000MHz;
the later probe above passed after idle. This was a verification timing issue, not a clock fault.
