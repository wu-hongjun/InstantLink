# Bridge transient Bluetooth warnings

## Scope

Investigate the Bluetooth warnings remaining after plan 093. Preserve automatic reconnect,
status freshness and authentication recovery; validate on the installed Pi with status requests
only and no film. Keep genuine faults visible while removing duplicate reports and incorrect
diagnostic claims.

## Baseline evidence

The six warning records represent three failed connection attempts. Each native terminal callback
reported `BLE error: BLE link disconnected during GATT setup` during characteristic lookup.
The first two followed service/BlueZ restoration; the third followed an external Disconnect.
All recovered automatically. The backend and controller each emitted a warning for the same
attempt, and generic FFI error text obscured the native cause.

The provider also supplied empty scanner diagnostics for BLE setup errors even though it had not
performed a separate scanner pass. This incorrectly reported that the selected Printer was absent.
Native readiness checks queried fresh BlueZ state and detected an actual dropped connection;
the investigation provides no evidence that those checks should be bypassed or weakened.

## Implementation and validation

Source fixes, independent review, matched status-only hardware checks and deployment evidence
will be recorded below. Only exact canonical setup-drop evidence qualifies for bounded transient
handling. Unknown, authentication and persistent faults retain warning-level visibility.
