# 070 — Bridge print cycle and SD cache audit

Date: 2026-10-12. Three independent agents audited receive/queue, review/UI, and image/native
Printer boundaries. Root verified the live deployment and benchmarked SD versus tmpfs cache.
No public config, sync API, native FFI ABI, protocol timings or App/iOS changes.

## Cycle coverage and ordering

| State | Ownership and required behavior | Audit result |
| --- | --- | --- |
| Boot / setup | CPU, UI and FTP can start alongside Bluetooth and optional Sync setup. | A dequeued item now waits for its chosen destination inside its shutdown-observed job. |
| Unpaired / offline / no film | FTP rejects an unusable Print destination before accepting STOR; Sync is independent. | Existing checks retained; no automatic resend after uncertain printing. |
| Receive / queued | Reserve upload pathname before open; pin completed source before handoff; preserve FIFO. | Prior overlapping-upload and retention repairs retained. Shutdown closes admission synchronously. |
| Sync | Accepted source remains owned until shared outbox setup completes. | Repair early dequeue loss; visible `Sync unavailable` if setup failed, original retained. Constructor handoff is joined on cancellation. |
| Model / metadata | Exact Printer model governs dimensions; enabled date metadata may overlap detection. | Cached model is a preparation hint, never a replacement for detection or explicit configuration. |
| Immediate | Skip review; prepare independently of BLE connect when a model hint is available. | Auto-model now benefits from the same overlap as explicitly configured models. Mismatch discards speculative output. |
| Initial review | Decode once; show photo before starting the full 1/5-second review interval. | Existing visible-countdown and cancel behavior retained. |
| Edits / tools | First interaction requires manual confirmation; coalesce edits to latest state. | Unchanged edits now skip worker/encode; bounds and unsupported directions still stop the timer. |
| Accept during update | Freeze accepted edit and retain its preparation/cache ownership. | Repair SELECT cancelling the cached worker and triggering an unnecessary new HIF decode. BACK/shutdown still cancel safely. |
| Superseded review | Newer state/session owns the screen. | Confirmation loop rechecks ownership before repaint, preventing late Preview over Printing/error/new session. |
| Lock / wake | Shared physical/virtual state persists; active work retains maximum CPU while dark. | Existing lock, unlock, no-film and cancellation regressions pass; no new GPIO action is implied. |
| Prepare / native handoff | Verify actual model and pass matching prepared bytes. | Python handoff reuses the latest edited bytes; core still performs native JPEG preparation. |
| Download start / chunks / end | Printer command lock and ordered ACKs preserve transaction integrity. | Kept serialized; ACKs lack chunk identifiers suitable for multiple in-flight chunks. |
| LED / execute | Existing handoff LED and model pre-execute delay precede PrintImage. | Unchanged pending physical validation; optional LED timeout/overlap remains a follow-up opportunity. |
| Success / failure / busy | Drain scheduled progress before terminal screen; never blindly resend. | Existing Error/no-film/stalled and navigation-preserving Printed notice retained. Sync-only errors no longer restart Printer polling. |
| Shutdown | Close admission, release queued ownership, join active workers and close resources in order. | Repeated outer cancellation now joins one shielded teardown; delayed Sync construction cannot escape cleanup. |

The visible default remains **Review → Printing → Home**, with a brief Printed notice. Manual,
immediate, one-second and five-second confirmation modes remain supported. The single image
consumer and large-image worker preserve film order and bounded memory; unrelated FTP, input,
network and status work continue independently.

## SD-card experiment

The live Pi mounts `/tmp` as **tmpfs**, with a 232 MiB limit; `/var/lib/InstantLinkBridge` is
on `/dev/root`, about 57 GiB total with 48 GiB free at measurement. The current normalized
source cache is therefore already memory-backed. [Linux tmpfs documentation](https://docs.kernel.org/filesystems/tmpfs.html).

Controlled interleaved trials use the same real 11.26 MB Sony HIF, Square model, saved Vivid
settings and stock 1000 MHz. Only the parent's temporary cache directory changes. The same
5,131,254-byte lossless BMP is written under `/tmp` or a temporary SD directory. Four edits
per trial, **tmpfs / SD / SD / tmpfs**, have exact matching JPEG and decoded RGB hashes.

| Edit-cache location | Samples | Mean | Range |
| --- | --- | --- | --- |
| tmpfs | 8 | **0.665 s** | 0.659–0.670 s |
| SD, file pages still cached | 4 | **0.667 s** | 0.659–0.670 s |
| SD, file-page eviction requested | 4 | **0.876 s** | 0.864–0.894 s |

For the SD eviction trials, the isolated BMP was fsynced, then `POSIX_FADV_DONTNEED` requested
eviction for that file only. This is advisory; no whole-system cache was dropped. Durable
flush cost was **0.245 / 0.259 s**, outside edit timing. Clock samples for every retained run
read 1000 MHz; no throttling. Probes removed their files and restored dark idle to 600 MHz.
[Complete sanitized trials](../assets/bridge-audit-070/sd-cache.json).

**Decision:** keep the active-photo cache in tmpfs. Moving it to SD does not increase hit
rate in today's one-photo review flow and makes reads slower when pages are evicted. A bounded
persistent SD cache could skip HIF decoding for a previous photo revisited after expiry, another
photo or restart. That requires a real revisit/reprint workflow and versioned invalidation;
it does not accelerate the first decode of a new camera photo. A normalized-source cache must
identify exact source content, decoder/normalization version, model and working bounds. A final
JPEG cache must additionally identify all edits, fit, quality, Looks, Correction and overlays.
No persistent SD cache, swap change or boot configuration change was introduced.

## Quality guard

The installed [heif-thumbnailer v1.19.8](https://raw.githubusercontent.com/strukturag/libheif/v1.19.8/examples/heif_thumbnailer.cc)
selects an embedded thumbnail when present and only downsizes. The previous HEIF path ignored
the model's minimum source edge and could silently enlarge a tiny thumbnail for printing.
It now closes an undersized result and retries once with `-p` at the same bounded working size.
Adequate thumbnails keep the same command and pixels. An intrinsically small primary remains
printable; fallback failure uses the existing friendly decode error. The decoder timeout and
killable process group cover the retry. A regression cancels a real blocked primary-decoder
subprocess, clears the working cache and verifies the next job can proceed.

## Remaining native/hardware opportunities

- The Rust core still reloads, resizes and re-encodes the already prepared JPEG. A future
  validated prepared-JPEG core/FFI entry point could reduce CPU work and JPEG generation loss.
  It needs exact detected-model, RGB/JPEG integrity, dimensions and byte-budget guards. Mini
  Link 3 must still receive exactly one vertical flip; Mini/Square/Wide passthrough and Link 3
  must not be conflated. Native elapsed time and physical output are not measured this pass.
- The optional handoff LED uses the generic ten-second response timeout. Bounding its wait or
  overlapping it with the mandatory pre-execute delay may save latency, but its relationship
  to Printer firmware must be verified. Protocol chunk delays remain: the reference 102,303-byte
  Square image has 57 chunks, 8.55 seconds of configured packet sleeps plus one-second
  pre-execute delay before other transport/ACK overhead. These are code-derived, not a measured
  physical total.
- Core returns at successful PrintStatus. Code does not separately observe mechanical ejection.
  Two queued physical photos should establish whether success already implies readiness for
  the next DownloadStart. No mechanical/busy regression is asserted without that evidence;
  automatic retry after uncertain send would risk duplicate film consumption.
- Fresh FTP address probes and per-photo paired-device lookup are small remaining candidates;
  measure their actual contribution before adding stale network/identity caches.

The saved Printer remains off/not advertising, so no BLE send, ejection, new Sony Wi-Fi upload
or battery discharge is claimed. Hardware/OS: Pi Zero 2 W Rev 1.0 / Waveshare ST7789 / X306
2300 mAh, Debian 13.2, kernel 6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82, Bridge 0.1.17;
Sony a7C II profile, Instax Square INSTAX-52006924.

Final local gates, deployment and on-Pi changed-path checks are recorded below after verification.
