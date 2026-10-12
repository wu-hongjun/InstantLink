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
