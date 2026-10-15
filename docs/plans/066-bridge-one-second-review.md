# 066 — Default to one-second print review

Date: 2026-10-11. Scope: default review delay, shared Bridge/App management settings and deployment.

The user requested a shorter default instead of a five-second pause. New and missing configuration
now use **Review 1s**. Bridge and App offer Confirm each, Print immediately, Review 1s and Review 5s.
Explicit existing manual/immediate/five-second choices remain supported. The connected Bridge's
previous five-second delay was changed to one second for this request.

The Python config/parser, orchestration fallback, example config, LCD label/options, manager
validation and App model/draft/options/localizations must agree on the new value. Legacy positive
non-option delays map to the new default; invalid booleans remain invalid. Manager validation
accepts only 0/1/5/off. The countdown still begins after the prepared photo is visible, and edits
require manual confirmation. No print transport, image pipeline, CPU tier or sync contract changes.

## Validation and deployment

Clean runtime **`4574aa9`** was deployed. **1,324 Bridge tests** and **156 App tests** passed,
with Ruff, touched-file formatting, strict mypy (65 source files), whitespace and strict MkDocs.
The new App label is present in all 12 locales; the global localization checker retains its
pre-existing discrepancies. The initial full Bridge run found three old dispatch assertions
expecting five seconds; these were updated to one second and the whole suite passed. The App
portion of the pre-commit gate passed before that correction and was reused for the commit.

The live config was updated under `ib`, changing only the workflow delay from 5 to 1. Bridge
and manager were restarted and are active with Bridge NRestarts=0. An on-Pi controller smoke
loaded this saved config and supplied a synthetic prepared photo with NullDisplay/NullInput:
the first review title was **Print in 1s**, workflow label **Review 1s**, and acceptance occurred
**1.002 seconds after the photo frame**. No Printer sender was used and no film was consumed.
Hotspot remains at 192.168.8.1/24; throttling is 0x0.

Hardware/OS: Pi Zero 2 W / Waveshare ST7789 / X306 2300 mAh, Debian 13.2, kernel
6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82, Bridge 0.1.17. This verifies the saved setting
and controller timing; it is not a new physical-print benchmark. The App source/options were
updated and tested; no App release was installed on this Mac.
