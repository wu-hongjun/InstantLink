# 064 — Recover Bridge Wi-Fi after startup failure

Date: 2026-10-06. Scope: Bridge hotspot recovery and truthful LCD status.

## Observed failure

The LCD reported `Setup needed` / `Next action Bridge Wi-Fi off`. USB SSH was available,
NetworkManager and the Bridge were active, and the Wi-Fi radio was enabled. However, no
`wlan0` interface existed. Kernel boot logs recorded a corrupted SDIO RAM image, failed
NVRAM download and an MMC inhibit timeout before the Bridge's runtime power tiers began.
`vcgencmd get_throttled` returned `0x0`; this provides no evidence of a downclock or
undervoltage cause.

Reloading `brcmfmac` restored `wlan0`. Activating the existing hotspot with the root Wi-Fi
helper restored `192.168.8.1/24`, using the saved SSID/PIN. The Bridge did not restart.
The old runtime applied Wi-Fi mode once at startup and never retried a failed activation;
the hotspot profile intentionally has autoconnect disabled to keep FTP modes deterministic.

## Implementation

- The existing root Wi-Fi helper enables the radio, then checks for `wlan0`. On a Raspberry
  Pi with no interface, it reloads the fixed `brcmfmac` module and waits up to ten seconds.
  Healthy interfaces are never reloaded. Existing constrained sudo permissions suffice.
- The shared controller schedules one detached recovery task for configured Hotspot mode.
  Startup/healthy grace is 30 seconds; failed attempts back off for 30, 60, 120 and then
  300 seconds. The task checks actual radio intent, serializes with explicit mode operations,
  checks persisted App network intent after its radio probe, and rechecks readiness after
  the helper returns. Missing expected IP never becomes ready
  just because the helper exits successfully.
- Active photo processing, printing, queued images and recent FTP traffic defer attempts.
  Stop and mode changes cancel recovery. Wired, Auto and Peer modes do not cause retries;
  an explicitly disabled radio stays disabled during background recovery.
- Physical and virtual LCD status share `Bridge Wi-Fi unavailable` wording, translated in
  English and Chinese. A missing address is not evidence that the radio was turned off.
  Setup readiness remains honest until the expected address returns.
- Cancellation terminates the root helper's active command and bounds Python output draining
  and reaping, so an inherited output pipe cannot freeze a mode switch or shutdown.

## Validation

Clean implementation commit `cad66aa` passed the normal pre-commit gate: **1,282 Bridge
tests**, Ruff and strict mypy (65 source files). Touched-file Ruff formatting, shell syntax,
whitespace and strict MkDocs also passed. An independent review confirmed the persisted-intent
and cancellation fixes. No App/iOS schema or API contract changed.

Shell recovery tests exercise healthy-interface preservation, recovery with/without a loaded
driver, refusal on other hardware, a bounded failed recovery and real child termination.
Controller tests cover
grace/backoff, asynchronous scheduling, state guards, explicit mode changes and shutdown.
Renderer tests preserve setup-needed behavior and translated copy. Hardware deployment and
automatic fault recovery await restoration of USB access; `cad66aa` is not yet deployed.
The manual recovery above succeeded
on Pi Zero 2 W Rev 1.0 / Debian 13.2 / kernel 6.12.47+rpt-rpi-v8, with Waveshare ST7789 LCD HAT
and X306 2300 mAh battery. Saved Instax Square was connected (film 6, battery 95%). No film
was consumed. Camera reconnection and a new 16-hour discharge test are not established here.
