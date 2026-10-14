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

Only exact canonical setup-drop evidence qualifies for bounded transient handling. The first two
unresolved setup drops are INFO; the third is WARNING. The episode survives session teardown,
same-target absence, unknown failures and case variants, clearing only after fresh status or
a different target. Unknown and authentication failures remain warnings themselves.

The backend retains native detail and stage in its log signature. A per-exception ownership flag
prevents a duplicate controller warning without suppressing failures from other providers.
BLE setup errors no longer invent an empty scan. Startup permits the existing two prompt retries
after a confirmed setup drop, then returns to normal offline cadence; repeated drops or absent
scans do not renew this allowance. A pending disconnect event retains recovery ownership.

Three subagents independently investigated, implemented and adversarially reviewed the work.
Review fixed a misplaced failure-reason reset and a logging test fixture; root review also caught
an allowance reset after intervening absent scans. All received regression coverage. The final
full suite passed **2,450 tests**, with eight expected Mac GPIO warnings. Ruff formatting of
158 files, Ruff lint, strict mypy of 68 source files, diff checks and strict MkDocs passed.
The producer ran 352 affected tests; the independent reviewer ran 368 broader checks and the
final amended 65-test status suite. No Rust, protocol, image, FFI ABI or configuration changes.

Clean `aa852e1` installed through the normal deployment script, which restarts BlueZ, manager
and Bridge. Loaded source hashes match the independent review; FFI remains
`b91cf3fdd128b314cbcb952037e686514023371fe960a1c7d8ed4562d9ea1175`.
Initial installed health: Bridge PID 11373 and manager 11371 active with zero automatic restarts,
FTP 220/200, backup socket active and no runtime warnings. Startup was correctly awake at
1,000 MHz. The attempted live baseline timed out before issuing Disconnect because the Printer
was offline; historical plan 093 timings are contextual, not a matched speed comparison.

Installed automatic screen-off settled at 600 MHz/powersave/GPIO 24 low. Its full current-PID
journal contained 24 records and no warning/error matches. A second 85-second readiness probe
also timed out before issuing Disconnect because the Printer remained unavailable. Neither
probe issued any Printer command beyond the normal service's discovery/status activity.
Live installed reconnect remains **pending Printer availability**; no physical contact,
Printer power-cycle, fresh film-count comparison or reconnect-speed claim is made. No film used.
Hardware unchanged: Pi Zero 2 W Rev 1.0/ST7789/X306, Debian 13.2/kernel 6.12.47/BlueZ 5.82,
Link Square INSTAX-52006924.

Public evidence: [plan 094 audit assets](../assets/bridge-audit-094/README.md).
