# Plan 094 validation evidence

Three agents investigated, implemented and independently reviewed the transient Bluetooth fixes.
No raw journal, pairing key or private configuration content is included here.

The investigation suggested earlier escalation. The final reviewed policy allows two exact native
setup drops at INFO, matching the existing two-retry recovery burst, then warns on the third
unresolved drop. Same-target absence and other failures do not reset that allowance.

The final full Bridge suite passed 2,451 tests, with eight expected Mac GPIO fallback warnings.
Ruff formatting (158 files), lint, strict mypy (68 source files), diff checks and strict MkDocs passed.
The independent reviewer ran 370 affected checks after the recovery logging amendment.

## Initial evidence and rejected probes

`installed-health.json` records the initial aa852e1 installation, before Printer availability.
Its readiness probes timed out before Disconnect. `initial-live-health.json` records a later
connected attempt whose observer timed out on identical status logged only at DEBUG. That
observability gap was fixed and independently reviewed; this probe is not an accepted reconnect.

## Accepted installed checks

`reconnect-1.json` and `reconnect-2.json` measure external Disconnect dispatch to accepted fresh
controller status: 11.159 and 7.367 seconds. All 32 samples retained PID13213, 600 MHz/powersave,
backlight GPIO24 low and FTP220/200; film zero unchanged. The second encountered an actual setup
drop, preserved with native stage/detail at INFO before automatic recovery.

`accepted-health.json` records clean 7c312ad with reviewed hashes, connected/fresh Printer, active
services/backup socket and no warnings/errors in its complete 132-record current-PID journal.
No film, image or actuator commands. No manual internal lock-state/physical-contact/Printer
power-cycle test or matched speedup claim. Transient physical drops have not been eliminated.

Independent final evidence review passed (`live-review.json`). Root then removed both owned
remote helper files and confirmed Bridge, manager and the production backup socket remained active.
