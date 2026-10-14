# Plan 095 evidence

`native-discovery-cadence.json` measures production controller/provider/Rust FFI on the Pi with
an unmatched synthetic Printer name and NullDisplay. Bridge service was stopped for the probe
and restored by an EXIT trap. No real Printer connection, key change, print, image or film command.

Awake starts were 1.378–1.392 seconds apart, including a one-second scan plus driver overhead.
Dark discovery started after 30.002 seconds with a five-second window at 600 MHz. First unlock
input woke the scan in 40.8 ms; CPU was at 1 GHz when that press completed. The scan can start
while the CPU helper is warming, before the remaining two presses complete unlocking.

`lcd-preview.png` shows candidate rendering with synthetic credentials and Mac font fallbacks,
not photographs of the physical panel. Both empty-film modes and English/Chinese large text were
visually reviewed; Network and Screen groups fit the 240×240 viewport.

Local final source gate: 2,481 Bridge tests, eight expected Mac GPIO fallback warnings; 602 focused
checks, Ruff lint/format (159 files), strict mypy (68 files) and strict MkDocs. Unrelated preexisting
App localization failures were observed during read-only contract review; App sources/resources
were not changed and those checks are not included in this Bridge validation claim.

Installed automatic boot/reconnect results will be recorded after Printer availability.
