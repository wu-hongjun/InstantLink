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

Installed automatic boot/reconnect checks passed after Printer power-on:

- `boot-result.json`: UI ready **14.138 s**, FTP/core ready **14.152 s**, fresh Printer status
  **20.041 s** from kernel startup, without a button action. Pre-kernel firmware time is excluded;
  this is not a matched availability-controlled speedup comparison. Film **10→10**.
- `reconnect.json`: external BlueZ Disconnect → fresh automatic status **8.885 s** with the
  normal service's screen off. All 14 samples retained PID 502, 600 MHz/powersave, backlight low
  and FTP 220/200. One canonical GATT setup drop recovered through a prompt retry. Film **10→10**.
- `accepted-health.json`: Bridge/manager active with zero automatic restarts, Printer connected,
  throttle `0x0`, backup socket active and reviewed source/unchanged FFI hashes. Complete Bridge
  PID journal had 83 records and zero warning/error matches at capture.
- `running-log-review.json`: wider Bridge/manager/Bluetooth review retained two BlueZ notices
  and one manager hotspot-bind retry, which became listening after **1.004 s**. Hotspot HTTP
  answered afterward. System boot has 22 platform warning-priority records; no global warning-free
  claim. No image, print or Printer actuator commands were used.

The initial boot observer mistakenly classified GPIO initialization as button input. Rechecking
the retained journal's actual `ui.input action=` events accepted the same reboot; no second reboot
was needed. Production service stayed running. These checks verify normal automatic screen-off
idle; internal manual-lock flags and physical button contacts were not inspected.

`handoff-health.json` records the final docs-only deployment of clean `c1aa432`, preserving Bridge
502/manager661 and zero automatic restarts. The Printer subsequently disconnected at 17:12:29,
about five minutes after recovery, and the next scan found no advertisement. The Bridge received
the disconnect event and resumed discovery with no warning/error records. Physical Printer
power-off was not observed; the final connected state is false, distinct from the accepted live
checks above. FTP, 600 MHz/powersave/backlight low, backup socket and throttle0x0 remained healthy.
