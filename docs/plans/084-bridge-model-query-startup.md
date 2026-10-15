# Bridge startup model-query recovery

## Goal

Reduce the startup delay when the Printer does not answer the first ImageSupportInfo query.
Preserve automatic reconnect, model-specific preparation/orientation, authoritative dimensions,
command serialization and failed/cancelled session retirement. Hardware validation uses status
requests and external disconnects only; no film.

## Approach and acceptance

Subagents implement and audit a single retry of this read-only capability request after a
short first response window, within the original ten-second response budget. One command lock
and delivery guard span both writes; terminal failure still retires the uncertain session.
No actuating command is replayed. Model detection retains queried dimensions and validates
known DIS identity conflicts. Ambiguous Link 3 hints fail safely instead of changing orientation.

Independent adversarial review covers late/duplicate replies, partial packets, no response,
write failure, cancellation/disconnect, unrelated commands and model/hint conflicts. Compare
baseline, candidate and installed warm startup, request counts, subsequent periodic freshness,
automatic reconnect at 600 MHz and logs. Preserve failed attempts and radio variance. Run relevant
local/ARM gates, deploy clean artifacts and restore normal service/remove owned fixtures.

Hardware: Pi Zero 2 W Rev1.0, ST7789 LCD, X306 battery; Debian13.2/Linux6.12.47+rpt-rpi-v8,
Python3.13.5/BlueZ5.82. Instax Link Square INSTAX-52006924. No physical film-quality claim.

## Source acceptance

Clean source **b2b6c8c** implements `Transport::query_image_support`. The production BLE
transaction sends the eight-byte capability query, waits up to one second for its reply, and
resends once only after a response timeout. Both writes and receives share the original
ten-second total deadline, command lock and delivery guard. Healthy queries still send once.
Write failures, confirmed disconnects and cancellation do not trigger replay. Terminal failure
retires the uncertain session. Custom transports retain their existing transaction behavior.

Independent review found and fixed partial-frame retention when the outer first-response timer
cancels receive before its inner cleanup. The assembler is reset before each model-query write,
while queued complete notifications remain available. A real-channel regression combines an
incomplete first reply, complete retry reply, duplicate model reply and fresh battery status.
Late duplicate capability replies cannot satisfy status selectors.

Dimensions remain authoritative. ASCII-trimmed exact `FI033` requires 600×800 and selects Mini
Link 3; exact `FI017` requires 800×800 Square. Conflicts and ambiguous formerly recognized Link 3
strings fail safely instead of changing orientation. Other unknown/missing hints use dimensions.
DIS reads require the canonical service; normalization remains ASCII-only throughout. Model
specifications, JPEG preparation, image bytes, transfer pacing and C ABI are unchanged.

Normal hooks passed **322 Rust tests plus 1 doctest**, **1773 Bridge tests** (27 existing warnings),
Rust formatting, strict production workspace Clippy, Ruff and strict mypy (67 modules). Header drift and
strict MkDocs passed. Independent core suite (196 tests) passed. Pi ARM tests: 8 model-query and 47 device tests.
The first formatting gate caught a final concurrent formatting change; corrected and rerun
through normal hooks. Source hashes and manifests are in `source-validation.json`.

## Hardware benchmark and deployment

Status-only checks completed on the hardware above, with no image/print commands or film.
Warm startup timing below is **first status attempt to first successful completion**, not a
cold boot measurement. Each successful request used three fresh status commands. Subsequent
periodic requests also used three hardware reads, with advancing completion timestamps.

| Run | Initial status completion | Model-query behavior |
| --- | ---: | --- |
| Baseline1 | 3.673s | Healthy, one query |
| Baseline2 | 32.271s | First query timed out; later connection recovered |
| Candidate1 | 3.734s | Healthy, one query |
| Candidate2 | 3.703s | Healthy, one query |
| Candidate3 | 3.866s | Healthy, one query |
| Installed | 4.326s | Healthy, one query |

The missed-first-reply case did not recur in the three candidate warm starts or installed
startup. These observations do **not** measure live retry speedup or prove all startup timeouts
are eliminated. Deterministic paused-time tests drop the first reply and return a model reply
140ms after resend: completion at 1.140s, exactly two queries and no third write. Silent links still
reach the original ten-second deadline and retire safely. No DIS-only model shortcut is used.
Baseline1 collection began after status was already ready; its original 14.669s collection
latency is retained, but the table derives 3.673s from actual attempt timestamps.

Candidate and installed external-disconnect recovery took 11.828s and12.486s. Each included a
scan miss followed by automatic recovery. All 33 observations in each run remained locked,
not unlocking, at 600 MHz and camera-ready. Radio/discovery variation prevents a universal total
reconnect speedup claim. Exact FI017/Square and MTU 247/payload 236 were retained. Installed
same-button triple unlock, nonblank LCD at 1000 MHz, relock at 600 MHz and status pause/resume passed
through production abstract input actions and the physical LCD; button contacts were not actuated.
Physical film quality was not retested; model preparation byte/orientation tests passed.

Clean Python/native **b2b6c8c** deployed. FFI SHA256
`9e31f99896ece2b687652bfdd0e80318a349cdb387c4e8c2d44ef35fa0d34031`; CLI
`1068fcb591c94e5a2b8bb888361230ade931b8da5b529528500c58edba4ce38e`.
Candidate and installed observer logs had zero matched warning/error/panic messages, including
successful reconnect after scan misses. Baseline2 timeout remains recorded. Observer/drop-in/
socket, candidate library and owned ARM test binary removed; normal service restored.

Evidence under `docs/assets/bridge-audit-084/`: source validation, live benchmark, independent
adversarial review, installed UI smoke, final health, cleanup and running-log review. Raw journals
remain private. Remaining costs include advertisement/GATT availability, BLE handshake and initial
watch registration. A future occurrence where both model replies are lost should retain its
packet/connection trace before changing the retry or teardown policy.

Final normal service verified at **18:54:58 EDT**: PID34446/manager34001 active, NRestarts0,
Printer connected, 600 MHz powersave/GPIO24low,43.470°C/throttle0x0, GPIOv2,
hotspot/USB/FTP220/200 healthy. Clean deployment/native manifests and loaded library hashes
match b2b6c8c. Final normal log has zero matched warnings/errors/panics. Whole current-boot
Bridge/manager service review covered 9294 records and retained 134 historical matched issue
messages, including two earlier native panic episodes. Task084 baseline2 warnings are retained;
candidate, installed observer and restored normal processes have no matched issues. No kernel-log
claim. Independent source, hardware and final-health/log review passed. All owned fixtures,
including the final health script, are removed. See final-health.json, cleanup.json,
running-log-review.json and adversarial-review.json.
