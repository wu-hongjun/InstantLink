# 066 — Default to one-second print review

Date: 2026-10-11. Scope: default review delay, shared Bridge/App management settings and deployment.

The user requested a shorter default instead of a five-second pause. New and missing configuration
now use **Review 1s**. Bridge and App offer Confirm each, Print immediately, Review 1s and Review 5s.
Explicit existing manual/immediate/five-second choices remain supported. The connected Bridge's
current five-second delay will be changed to one second for this request.

The Python config/parser, orchestration fallback, example config, LCD label/options, manager
validation and App model/draft/options/localizations must agree on the new value. Legacy positive
non-option delays map to the new default; invalid booleans remain invalid. Manager validation
accepts only 0/1/5/off. The countdown still begins after the prepared photo is visible, and edits
require manual confirmation. No print transport, image pipeline, CPU tier or sync contract changes.

Validation and on-device deployment results will be recorded after completion. The existing Pi
uses a Pi Zero 2 W / Waveshare ST7789 / X306 2300 mAh with Debian 13.2, Python 3.13.5 and BlueZ 5.82.
No film will be consumed by the configuration verification.
