# Bridge Bluetooth disconnect events

## Goal and evidence

Plan 080 measured 9.4–9.8 seconds waiting for the next status poll after a link drop.
Use disconnect events on the existing agent-owned BlueZ bus to prompt that check,
keeping periodic status as a fallback and preserving bounded reconnect retries.
No film is used in validation.

## Boundaries

- Authenticate unique BlueZ sender, selected device identity, owner and lifecycle.
  Handle connection loss/removal/daemon changes conservatively; unrelated or malformed
  messages cannot initiate recovery.
- Callbacks only coalesce a wake request. Status fetching remains serialized with
  printing and recovery; callbacks do not disconnect, delete bonds or replay commands.
- Retain events arriving during a fetch. Retired generations/selection changes and
  shutdown disarm subscriptions. Own cleanup signals cannot create a retry loop.
- Keep ten-second status checks as fallback, normal offline cadence, two prompt retries,
  print pause/cancellation, screen behavior and 600/1000 MHz tiers.
- Reuse subscriptions while online. No per-poll snapshot, new idle queries, extra polling,
  Rust/FFI change, public configuration field or sync-contract change.

## Validation

Independent producer/consumer implementation and adversarial review; authenticated
signal/lifecycle, lost-wake, print-pause, cancellation, retry and fallback tests.
Baseline/candidate/installed real status-only disconnect/reconnect timing; retain misses
and separate target visibility from software latency. CPU samples, actual LCD/input/power
checks, full running-log review, clean deployment and removal of owned test resources.

Hardware: Raspberry Pi Zero 2 W Rev1.0 / ST7789 LCD / X306, Instax Link Square
INSTAX-52006924. Debian 13.2, Linux 6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82.

## Source acceptance

Independent producer and consumer work plus adversarial review resolved three issues:

- Stale disconnected iOS/Android aliases could invalidate a healthy connection. Resolve
  one live path; ambiguous identity retains periodic fallback.
- A failed watch setup could repeat snapshot IPC/warnings on every successful poll.
  Attempt once per connected episode; a real transition/generation permits another attempt.
- Detected model metadata could differ from the captured selection and reject its callback.
  Match address and name, allowing model updates while rejecting either selection change.

Final independent review passed 36 targeted cases, including independent regressions.
Agent suite 48 and controller/runtime suite 288 passed; strict mypy 67 sources, Ruff,
touched formatting and whitespace checks passed. Native/FFI, image processing, protocol,
configuration and sync contracts are unchanged. Full final path-scoped gates run at commit.

## Early hardware observations

The first baseline harness accidentally started protected wake from automatic screen-off.
It recovered in 15.536 s but failed the locked at 600 MHz condition; excluded and retained.
The aligned baseline passed at 12.401 s, first new fetch 9.885 s after disconnect request.
Early candidate runs woke from the actual BlueZ signal in about 260 ms, with full recovery
observed by 19.558 s and 13.963 s after failed scans/target matching. Target visibility varies:
these demonstrate wait removal, not a universal full-flow speedup. All accepted rows stayed
locked at 600 MHz/camera-ready. No film used. Final installed acceptance follows below.

## Final deployment and acceptance, 2026-10-13

Clean Python source **ec960c24db99ae571bfdd06fcc97d7867e2577c9** is installed under
`/opt/InstantLinkBridge`. Rust CLI/FFI artifacts are unchanged from plan 080; native FFI
SHA256 `b67842fed5ce50b8b9389acdf7f55c5d2a7ad8859f30d5ec460307260dcbb06a`.
Evidence: `docs/assets/bridge-audit-081/` retains all accepted rows and the rejected initial
baseline, source review, LCD tests, CPU samples, cleanup and final normal health/log counts.

| Run | Recovery observed by | Disconnect request to first status fetch | BlueZ loss signal to fetch |
| --- | ---: | ---: | ---: |
| Aligned baseline | 12.401 s | 9.885 s | Not watched |
| Candidate aligned | 19.558 s | 2.771 s | 261.527 ms |
| Final candidate | 13.963 s | 2.725 s | 261.538 ms |
| Installed firmware | 12.888 s | 2.195 s | 261.527 ms |

The signal-to-fetch interval includes the intentional 250 ms recovery gap. BlueZ emitted
loss 1.934–2.509 s after the disconnect request. All accepted rows stayed locked at 600 MHz
and camera-ready. The aligned candidate had two failed attempts; final candidate and
installed each had one. The software wait is removed; visibility, discovery and handshake
still dominate variable total recovery. These runs do not establish a universal total-speedup.
Recovery times include observer/query sampling overhead. No image or print commands or film.

Connected idle CPU: three 20 s samples per runtime at 600 MHz. Baseline 1.950/0.350/0.400%
(mean 0.900% of one core); candidate 0.350/0.450/0.350% (mean 0.383%). Child CPU zero.
Separate starts/ambient activity and the elevated first baseline row prevent a universal
CPU, energy or battery-life reduction claim; no observed increase. No per-poll watch IPC.

Eleven kernel GPIO mock-to-production-input cases on the physical LCD/CPU passed: nonblank
wake to 1000 MHz, same-button triple unlock, different-button reset, debounce, held/rapid
presses, ten-second abandonment to dark 600 MHz and detach. Physical contacts were not
actuated; mock module was removed. Printing serialization/cancellation are mocked-test
coverage, not a physical print-quality test in this no-film task.

Final normal service at 09:45:22 EDT: Bridge PID 25926 / manager 25301 active, NRestarts 0;
Printer connected, 600 MHz powersave, GPIO24 low, 42.932°C, throttle 0x0, GPIO v2 input,
hotspot/USB up, FTP greeting 220 / NOOP 200. FTP probe uses the Pi's hotspot address and
does not measure camera upload/wireless airtime. Source/native hashes match. Owned observer,
source override, drop-in, socket and GPIO mock removed; normal executable restored.

Reviewed 4300 current-boot service journal records (41 for final normal processes); zero
normal application WARNING/ERROR. The 99 earlier warning/error records include historical
079/080 experiments, controlled baseline losses and harness faults; retained counts prevent
presenting the whole boot as clean. Raw journals stay private. No kernel-log claim.

Final gates: normal commit hooks **1724 Bridge tests**, 27 existing GPIO/deprecation warnings;
48 agent and 288 controller/runtime cases, strict mypy 67 sources, Ruff, touched formatting,
whitespace and strict MkDocs passed. Independent adversarial review passed 36 targeted
cases after all three findings were fixed. No outstanding source blocker.

Independent hardware-evidence review also passed: raw timing/state captures match the summary;
no deployment blocker. `final-normal-health.json` is the final 13:45 UTC connected capture;
`instantlink-events-installed-normal-health-081.json` retains the earlier 13:29 UTC offline
state, before the final power-on and installed recovery check.
