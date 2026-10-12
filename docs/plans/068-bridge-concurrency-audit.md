# 068 — Bridge concurrency audit

Date: 2026-10-11. Scope: Bridge startup, UI, photo jobs, sync outbox and Python FFI ownership.

The Pi Zero 2 W has four CPU cores. The runtime uses asyncio for I/O scheduling, executor
threads for blocking filesystem/system/FFI work, a killable image process, and the native Rust
runtime. Independent work must preserve response ordering, bounded memory, configuration
consistency and cleanup ownership. No public API/schema or image rules change.

## Stages and dependencies

| Stage | Independent work that overlaps | Required ordering |
| --- | --- | --- |
| Boot | CPU helper, FTP import/bind, Bluetooth agent | First UI/input and core READY wait for maximum CPU; Printer waits for agent; optional Sync starts after core readiness. |
| Settings Refresh | Network health and saved-Printer lookup | Apply only to the still-open page; repeated actions share one worker. |
| Network health | UI input, BLE work, FTP/sync transfers | Startup/poll/Settings/recovery share one probe; changed config or Wi-Fi activation invalidates and rechecks results. |
| About | Version/identity and metrics collection off the UI loop | Metrics wait for CPU baseline; one cached collector; no off-page or post-stop repaint. QR identity loads independently and never encodes a placeholder. |
| Preview | Printer model detection and enabled EXIF datestamp read | Decode/resize follows model; adjustment order is preserved; one large image worker. |
| Immediate print | Existing configured-model preparation alongside BLE connect | Detected model validates prepared image; transport commands/status/keepalive stay serialized. |
| Sync ingest | New file copy/hash alongside reads/acks of existing photos | Additions retain arrival order; publish/evict/index commit under metadata lock. Pending photos are not exposed. |
| Shutdown | Cancel all UI tasks together within one fixed six-second budget | Join owned sender/image/filesystem work before freeing resources or CPU boost; repeated cancellation cannot interrupt FFI grace or decoder cleanup. |

The single photo consumer preserves film order. FTP reception, HTTP streaming, GPIO/virtual input,
watchdog, network recovery and BLE monitoring already run independently of that consumer. Two
large HEIF/RAW pipelines are not admitted together on the 512 MiB board; their pixel buffers can
exhaust memory. Transforms that consume preceding output remain ordered. No unbounded worker
pool or speculative extra image was introduced. Tiny configuration/preset reads were reviewed;
no measured stall justified changing their persistence/rollback ordering in this pass.

## Ownership corrections

- Stop reaches pending review/preparation/send instead of waiting for a whole photo job.
  Sender cleanup finishes before releasing its CPU boost or shared backend.
- FTP bind and outbox-add threads are shielded and joined: cancelling an asyncio waiter cannot
  stop their socket/filesystem transactions. Captured FTP listeners stop even if startup is
  cancelled; hashing failures remove unpublished spool files.
- Image-worker close interrupts active internal preparation instead of waiting on the same lock
  for the entire job. New/queued work is rejected after close; process-group cleanup survives
  concurrent close and repeated caller cancellation.
- FFI cancellation retains the Printer lock until its blocking call completes or the original
  five-second restart deadline expires. Repeated cancellation cannot reset that deadline or let
  a second command enter early. A slow-print notice keeps waiting for the original job.

## Validation

Tests use mutual-start handshakes and held I/O/cleanup gates to prove overlap and ownership,
rather than asserting task creation alone. They cover shared network waiters, stale config and
activation, navigation during Refresh/About, model/EXIF overlap, sync reads/acks during hashing,
fixed shutdown deadlines, decoder descendants and repeated cancellation. Final local checks and
hardware observations follow after deployment. No new film print, camera transfer or controlled
battery discharge is implied by concurrency smoke tests.

Final local validation: **1,406 Bridge tests**, Ruff, strict mypy (65 source files), touched-file
formatting, whitespace and strict MkDocs passed. Three independent agents reviewed separate
boundaries and the integrated cancellation/startup paths. No App/iOS or FFI ABI changes; sync
API response/endpoint review confirmed the existing contract is unchanged.

## Deployment and on-device checks

Clean runtime **473a62c** deployed with its normal pre-commit gate passing. Hardware/OS:
Pi Zero 2 W Rev 1.0 / Waveshare ST7789 / X306 2300 mAh, Debian 13.2, kernel
6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82, Bridge 0.1.17. Native artifacts/dependencies
and saved configuration were preserved. The saved Printer is Instax Square INSTAX-52006924;
Sony a7C II remains the camera profile.

Software smoke ran under **ib** with production methods and injected gates, without GPIO input,
a camera upload or a Printer send. Settings Refresh overlapped two injected 250 ms waits,
completing in **271.9 ms**. Existing sync depth/get/ack completed in **3.1 ms** while a new
checksum was held. Repeated cancellation retained the FFI lock and kept the next operation
queued until the first worker exited. Real Linux image-worker/Pillow preparation produced an
800×800, 4,037-byte synthetic JPEG; closed workers rejected new work. These are controlled
concurrency checks, not a physical print-speed or battery benchmark.

First reboot: core ready **14.429 s**, UI **14.406 s**, FTP listener **14.076 s**, Bluetooth
agent **14.462 s**, hotspot receive-ready **18.797 s**, manager **19.344 s**. Systemd total
**17.152 s**. Results remain within plan 067's prior range: this pass adds no measurable
boot-speed improvement. Performance governor was applied at **13.464 s**, before the first UI
frame; normal idle later returned to powersave/600 MHz and GPIO24 low. Both services were
active with NRestarts=0; throttling 0x0; hotspot FTP 220 greeting and NOOP/200 passed.

[Sanitized measurements](../assets/bridge-audit-068/measurements.json) and
[About loading/ready frames](../assets/bridge-audit-068/about.png) accompany this record.
The About values are illustrative rendered states, not physical LCD photographs.

The user powered the Printer on for a second reboot. Core ready **14.224 s**, UI **14.205 s**,
FTP **13.870 s**, Bluetooth agent **14.262 s**; first valid Printer status **17.321 s**,
hotspot receive-ready **18.620 s**, manager **19.252 s**, total systemd **16.991 s**.
Both receive and Printer status were therefore available by **18.620 s** after kernel start.
BlueZ reported Connected=yes; subsequent status reads retained film **4** / battery **65%**.
This confirms fresh power-on boot reconnection at the latest runtime; no physical print was sent.
The preceding baseline had no advertising Printer and cannot establish a before/after connection
speedup. Approximate 4.5-minute Printer idle auto-off remains an external limitation.

Final live hotspot-loss test used normal automatic dark idle (no observation wrapper or injected
key). After deactivating the saved hotspot, its IP recovered in **29.75 s**.
Across **38 samples** including 10 seconds after recovery, CPU stayed **600 MHz**,
GPIO24 stayed low and BlueZ stayed connected. Bridge PID was unchanged; status reads continued
with film **4** / battery **65%**. These are sampled connection observations, not a claim that
every subsecond radio event was monitored. The temporary probes were removed; no config,
service wrapper or drop-in remained.
