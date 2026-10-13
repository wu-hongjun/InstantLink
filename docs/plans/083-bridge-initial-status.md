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

Live benchmark and task083 deployment are **pending**: the selected Printer was not advertising
and the power-on request has not been answered. No radio timing or real successful command count
is claimed. The previous validated Plan082 firmware remains installed. The baseline observer,
drop-in/socket and owned ARM unit executable were removed; normal service restored. Prepared
candidate source archive/library remain inactive under SD-backed /var/tmp for the live follow-up.
No image/print commands or film used.
