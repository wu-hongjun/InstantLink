# Bridge discovery and connection setup

## Goal

Reduce measured discovery/setup overhead while preserving automatic reconnect, model detection,
notification readiness, selected identity and command serialization. Real-device validation
uses status requests and external disconnects only; no film or image/print commands.

## Work

- Subagents audit native setup, Bridge bond gating and dependency lifecycle independently.
- Reuse the agent bus for a fresh bounded connected-identity check with conservative CLI fallback.
- Overlap read-only MTU discovery with the existing notification-settling floor; retain fallback.
- Correct the observed bluez-async message-stream cleanup panic without suppressing other failures.
- Retain active-scan/ambiguity/Android/liveness and retry behavior. Avoid optimistic cached
  advertising assumptions or additional idle polling.

## Acceptance

Record baseline/candidate/installed setup stage timings and full recovery, misses and variable
radio availability separately. Compare negotiated MTU/payload, low-frequency locked state,
status freshness, camera/network readiness, subprocess/query overhead and current running logs.
Use focused cancellation/race/fallback tests, full path-scoped gates, independent adversarial
review and normal deployment. Remove owned temporary fixtures and restore normal service.

Hardware: Pi Zero 2 W Rev1.0 / ST7789 / X306, Debian13.2, Linux6.12.47+rpt-rpi-v8,
Python3.13.5, BlueZ5.82; Instax Link Square INSTAX-52006924.

## Log audit correction

Plan081's final normal-process WARNING/ERROR counts were accurate for those severity strings,
but missed a native Tokio panic printed directly to stderr during service discovery at09:41:09
EDT. Printer connection and status subsequently succeeded. The full-log scan here includes
`panicked`, D-Bus cleanup failures and thread messages so a zero structured-error count is not
misreported as complete fault absence. This task investigates and fixes that cleanup race.
