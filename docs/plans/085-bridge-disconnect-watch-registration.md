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
