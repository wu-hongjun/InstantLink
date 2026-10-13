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
