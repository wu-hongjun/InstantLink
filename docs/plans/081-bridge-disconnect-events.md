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
It recovered in15.536s but failed the locked600MHz condition; excluded and retained.
The aligned baseline passed at12.401s, first new fetch9.885s after disconnect request.
Early candidate runs woke from the actual BlueZ signal in about260ms, with full recovery
observed by19.558s and13.963s after failed scans/target matching. Target visibility varies:
these demonstrate wait removal, not a universal full-flow speedup. All accepted rows stayed
locked600MHz/camera-ready. No film used. Final installed acceptance follows below.
