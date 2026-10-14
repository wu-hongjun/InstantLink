# Systemd startup and service ordering

## Scope

Audit the measured boot graph and improve LCD/FTP/Printer readiness without changing application
state, image/protocol code, CPU tiers, camera configuration or system security. Use status-only
Printer probes; no image-transfer, print or actuator command and no film.

## Bounded candidate

The existing Bridge waits for `dbus.service` to finish activation even though its listening
`dbus.socket` is available earlier. On the installed Debian13.2 system, that socket owns
`/run/dbus/system_bus_socket` and dbus-daemon inherits it through `--address=systemd:`. Change
Bridge ordering to `After=dbus.socket` with explicit `Wants=dbus.socket`, allowing Python imports
to overlap daemon startup. Keep default sysinit/basic/filesystem/shutdown dependencies, existing
parallel network/Bluetooth wants, notify/watchdog behavior and all service security unchanged.
The application still awaits the pairing agent before any Printer request.

The previous boot observed socket9.101s, daemon9.678s, Bridge process9.698s/boot marker12.931s;
this is an approximately0.58s ordering opportunity, not a promised complete boot improvement.
LCD framebuffer appeared9.333s, several seconds before application display construction.

Manager startup is unchanged. Its current network-online ordering does not invoke wait-online
on this image. Deferring manager behind Bridge READY could delay the rescue API until the
Bridge startup timeout and offers no demonstrated benefit: manager imports already start after
LCD/FTP. Global service disabling, CPU boost hooks, default-dependency removal and new socket
activation for manager are outside this bounded change.

## Adversarial requirements

Three subagents investigate, implement and independently review. Verify actual listening socket
precedes Bridge launch, pairing agent precedes Printer work and LCD uses the real framebuffer.
Removing daemon ordering also removes reverse shutdown ordering. Before acceptance, inspect the
previous candidate boot's shutdown journal for cleanup/unregister failures, native worker grace
expiry, forced kill or restart. Reject the candidate if shutdown reliability or readiness regresses.
No daemon-failure robustness claim is made from normal boot checks; bus authentication remains
an existing untimed operation in the Bluetooth startup branch.

Local deployment/ordering/listener tests and on-Pi systemd verification precede installation.
Normal reboot comparisons use kernel monotonic timings (exclude firmware startup) and no Bridge
button input. Collect LCD/FTP/core/agent/Printer and manager/hotspot milestones, film counts,
source/unit provenance, actual framebuffer/CPU state, isolated production FTP receipt, automatic
screen-off reconnect, complete application logs and broader service notices. Record observations
and rejected experiments with their limits after validation.

## Candidate rejected; original ordering restored

Clean80c2c8d passed2529tests/eight expected host GPIO warnings, Ruff/format165/mypy70 and
strict docs, plus actual Pi `systemd-analyze verify`. Its actual launch9.398s preceded daemon
readiness9.866s, establishing overlap. Baseline→candidate normal reboot: UI13.605683→13.595050s,
FTP13.582428→13.593595s, core13.616155→13.609813s. These single reboots show no meaningful
readiness gain; earlier launch was offset by import/system contention. No Printer was advertising
in either capture, so no connected-time comparison is claimed. The initial connected observer
timed out after reboot; the retained baseline component measurements remain valid.

Full candidate reboot cleanup succeeded6.728s/no forced kill, but D-Bus stopped before Bridge
finished. Two shutdown warnings were retained: waiting for native status worker and failed status
as BlueZ activation was refused during shutdown. These warnings are not attributed solely to the
candidate without a baseline control: BlueZ already shuts down independently. Removing the daemon
lifetime ordering is itself a regression risk. Independent review agreed to reject the change
rather than retain it for an11ms LCD observation. No warning was suppressed and no speculative
service disabling, priorities or manager serialization were added.

The final Bridge unit is restored byte-for-byte to a815fb1 (`After=dbus.service`), with regression
coverage protecting daemon startup/reverse cleanup ordering and independent manager rescue.
Final installed boot/LCD/FTP/automatic reconnect and live-log results follow after validation.
