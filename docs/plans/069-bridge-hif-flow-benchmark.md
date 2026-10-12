# 069 — Bridge HIF flow benchmark and ownership fixes

Date: 2026-10-12. Scope: Bridge camera reception, HIF preparation and review. No public
schema, sync API, native FFI or image-rule changes.

## Method and baseline

Measurements use the connected Pi Zero 2 W Rev 1.0 / Waveshare ST7789 / X306 2300 mAh,
Debian 13.2, kernel 6.12.47+rpt-rpi-v8, Python 3.13.5 and BlueZ 5.82. Saved Printer:
Instax Square INSTAX-52006924. Camera profile: Sony a7C II. Runtime baseline: 473a62c.
All timed image runs use stock maximum performance, 1000 MHz, with no concurrent benchmark.
Each probe restores the previous CPU governor; no source photo is altered.

The largest available camera HIF is 11,255,808 bytes, primary 7008×4672. The existing
thumbnailer supplies normalized 1600×1069 RGB, then Square preparation produces 800×800.
Saved settings are Auto fit, quality 100, Vivid (saturation 1.5), zero Correction, no date or
watermark, and one-second review. Square's 105,000-byte limit selects JPEG quality 76,
102,303 bytes. Exact JPEG and decoded-pixel hashes are recorded in the measurements.

| Baseline stage | Time |
| --- | --- |
| External HEIF decode and PNG write | 4.793 s |
| HIF opener including PNG read/RGB | 5.115 s |
| Fit/crop | 0.194 s |
| Colour adjustment | 0.088 s |
| JPEG size search, eight attempts | 0.327 s |
| Fresh child preparation, three trials | 5.892 / 5.785 / 5.798 s |

The opener consumes about 89% of the instrumented 5.725-second preparation. Per-process
peak RSS was 44,928 KiB for the Python probe and 38,996 KiB for its decoder child; these
are independent peaks, not a simultaneous whole-board memory total.

An isolated production FTP receiver uses hotspot address 192.168.8.1:2121 and temporary
incoming storage, with the real controller, image worker and review countdown. The client
runs on the same Pi, so traffic is locally routed and does not measure Sony Wi-Fi airtime.
Square identity/status are seeded; an observer captures the prepared JPEG at the sender
boundary. No BLE send or film ejection occurs. The actual Printer is off/not advertising and
cannot be remotely powered on. This bounds what can be validated without user action.

Three baseline trials reached that boundary in **7.069 / 7.033 / 7.006 s**: FTP upload
0.117–0.141 s, HIF/preview 5.858–5.945 s, review/lookup 1.005 s. Each photo prepares once;
the already prepared JPEG is reused at the sender boundary. Native Rust JPEG preparation
still occurs later; this probe does not measure it or establish physical print speed.

## Changes

- The parent image worker owns one temporary, lossless RGB BMP for the current HIF/model.
  Normalization precedes creative Looks, edit/fit and independent Correction, so reusing the
  source preserves output exactly. A bounded writer overlaps transformations and joins
  before JPEG encoding. Lazy Pillow sources load before any shared access.
- Identity includes canonical path, device, inode, size, mtime and ctime, plus Printer model
  and working bounds. Replacement, a new photo/model, corruption or decoding failure causes
  a fresh decode. Cancellation/close removes the cache; idle expiry is five minutes. Maximum
  working RGB is 1600×1600 (about 7.68 MB plus BMP header); the benchmark cache is 5,131,254
  bytes. Large image jobs remain serialized on the 512 MiB board.
- Successful preparation emits one structured `image.prepared` event with cache-hit state,
  source/transform/JPEG/total durations, byte count and selected quality. These are stage
  boundaries, not a CPU profiler; external decode remains inside the source stage.
- Queued/current originals are pinned against incoming age/budget pruning. Pins are released
  for success, failure, cancellation, overflow and shutdown. The 100-job queue is retained;
  its pinned originals can temporarily exceed the soft incoming storage budget.
- STOR reserves its canonical destination before opening it. Concurrent or queued/current
  destinations return 450 instead of allowing an already-open writer to change accepted
  bytes. Root and `/incoming` paths share this protection. Interrupted transfers release
  reservations. Shutdown rejects new uploads with 451 before awaiting teardown, drains queued
  ownership and retains abandoned files. A late/closed-loop handoff also releases its pin.
- Datestamps read nested ExifIFD DateTimeOriginal as well as the top-level value. All seven
  real HIF headers on this Pi store the date in the nested field. Metadata reads avoid pixel
  decoding; no extra image decode is introduced for the date.

## A/B and independent review

Interleaved uncached/cached/cached/uncached runs use the same real HIF, settings and fresh
killable child for each edit. Uncached edits take 5.75–5.80 s; cached edits take
**0.666–0.676 s**, about **88% less time**. First-photo preparation remains 5.78–5.93 s.
All corresponding JPEG bytes, decoded RGB hashes, dimensions and selected qualities match.
This improves repeated review edits; it does not speed up first-photo HEIF decoding.

Independent adversarial review reproduced a lazy HEIF decoder race, overlapping FTP writers,
late handoff/shutdown ownership leaks and exceptions before job cleanup. All were repaired.
Real-socket tests cover overlapping uploads, separate root destinations and interrupted retry;
unit/integration tests cover review retention, queue overflow, cleanup, metadata, cache source
replacement, model/fit/orientation, corruption, expiry and cancellation. The final review
found no remaining P1/P2 issue. A minor timing-boundary caveat was also corrected by eagerly
materializing normalized pixels before recording the source stage.

## Remaining limits

First-photo HIF decoding is still the dominant CPU cost. Lowering source resolution or forcing
a different thumbnail selection could change print quality, so neither was adopted without
quality evidence. JPEG size search is comparatively small and retains its exact output rules.
Sony Wi-Fi transfer, native BLE send and mechanical ejection require an awake Printer/camera;
their physical duration remains unmeasured in this pass. No claim of improved battery runtime,
whole-flow physical print speed or film colour validation follows from the software timings.

## Final deployment and validation

Clean runtime **738a088** deployed with native artifacts, dependencies and saved configuration
preserved. **1,448 Bridge tests**, Ruff, touched-file formatting, strict mypy (65 source files),
whitespace, strict MkDocs and normal pre-commit passed. Independent final review confirmed the
lazy-source timing correction and found no new correctness or material performance risk.

All seven saved HIFs passed on the deployed runtime. First preparation **3.103–5.802 s**;
cached edits **0.649–0.703 s**; uncached corresponding edits **3.146–5.875 s**. Every edit
matched exact JPEG, decoded RGB, dimensions and quality. All 621 clock samples across the 21
preparations read 1000 MHz; final benchmark temperature 48.850°C, throttling 0x0. Cache cleanup
on worker close passed. Date metadata was present in all seven files: first opener registration
and header read **247.6 ms**, subsequent reads **16.9–28.7 ms**. An earlier dataset trial had
an idle CPU transition and was excluded from performance results; its parity still passed.

Deployed FTP/controller replay: **7.106 / 7.038 / 7.035 s** to sender boundary, HIF/preview
**5.977 / 5.897 / 5.902 s**, review/lookup **1.004 / 1.005 / 1.005 s**, one preparation per
photo. All output hashes matched the baseline and all 211 clock samples read 1000 MHz. These
fresh-photo times remain within variation of the baseline; no improvement is asserted.

Additional real-socket checks under ib on the Pi verified root and incoming overlapping STOR
rejection, queued byte preservation, separate root destinations, interrupted retry, shutdown
451 and cleared pins/reservations. Production services remained active with NRestarts=0 and
unchanged post-deploy PIDs. Hotspot and USB addresses, authenticated FTP 220/NOOP 200 passed.
Final dark idle was restored to powersave/600 MHz, GPIO24 low, throttling 0x0; no working cache
or benchmark listener remained. Printer scans continued to report no advertising device.

[Sanitized measurements](../assets/bridge-audit-069/measurements.json) include complete
trials, settings, hashes, versions and final service state. Photos and credentials are excluded.
BLE/film, real Sony transfer and battery runtime remain outside the measured boundary.
