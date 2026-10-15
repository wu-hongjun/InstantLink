# 072 — Live HIF-to-Printer benchmark

Date: 2026-10-12. The user powered on the saved Instax Square Printer. The unmodified installed
Bridge **`7249d4e`** automatically reconnected, reporting film 4 and battery 65%. Native artifacts
remain the clean `6ca7035` build; FFI SHA-256
`8d5ee8081dc297f9c588038410941433d3f72a5eebe9b8c5f688dad476e5f75d`.
No production code, settings, protocol delay, service restart or native artifact change this pass.

## Method and boundaries

One saved Sony a7C II HIF (`DSC02697.HIF`, 11,255,808 bytes, primary 7008×4672) was uploaded
once with a unique filename to the production FTP listener at the hotspot address. This was a
same-Pi local-route replay: it exercises real FTP admission, queue, physical/virtual UI flow,
image worker, one-second review, native prepared-JPEG export, BlueZ and physical Square Printer.
It does **not** measure camera Wi-Fi airtime. Existing Auto fit / Vivid saturation 1.5 / neutral
Correction / requested quality 100 settings were retained. The existing byte budget chooses 76.
No retries or additional sheets were used.

A temporary btmon observer captured host/controller traffic without changing the runtime or
Printer transaction. An offline parser checked every reconstructed Instax packet checksum,
57 ordered data indexes, matching successful ACKs and zero padding after declared JPEG size.
It reassembled the actual outgoing JPEG. Monitor data had zero reported drops. Journald and
btsnoop timestamps were correlated with the FTP client's clock; benchmark boundaries use
journal observation times, with native phases measured directly from HCI traffic.

Hardware: Raspberry Pi Zero 2 W Rev 1.0 / ST7789 LCD / X306 2300 mAh, Debian 13.2,
Linux 6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82, Bridge 0.1.17; Instax Square
INSTAX-52006924. All 128 retained CPU samples during the boosted job were **1000 MHz**;
throttling remained 0x0. This is one measured print, not a latency distribution.

## Results

| Stage | Time | Boundary |
| --- | --- | --- |
| Local FTP upload | 0.153 s | Client STOR start through 226 |
| Dequeue through JPEG ready | 6.618 s | Includes CPU wake / worker setup; pipeline itself 5.850 s |
| Image source opening | 5.222 s | Worker stage log; dominated by HIF decoding |
| Transform / JPEG encode | 0.297 / 0.331 s | Worker stage logs |
| JPEG ready through native job start | 2.060 s | Includes visible 1-second review, UI and Printer lookup |
| Job start through DownloadStart | 0.025 s | Wrapper/model checks and strict native JPEG validation |
| DownloadStart through DownloadEnd ACK | **21.811 s** | Actual successful 57-chunk BLE transfer |
| LED acknowledgement | 0.026 s | Optional handoff LED answered promptly |
| LED send through PrintImage send | 1.030 s | Includes LED ACK and required 1-second pre-execute wait |
| PrintImage send through PrintStatus ACK | 0.031 s | Command accepted; not mechanical ejection |
| Native job start through Bridge completion | 23.151 s | Includes transfer and terminal callback/UI drain |
| **FTP STOR start through Bridge completion** | **32.005 s** | 31.852 s after upload completion |

Film changed **4 → 3**, and subsequent live status polls confirmed film 3. The first film-3
poll was about ten seconds after the Bridge's completion log. The Bridge/native success event
means successful PrintStatus; there is no mechanical-ejection sensor or measured film-development
interval. Do not label 32.005 seconds as time until developed film is ready.

No comparable full-print run of the old firmware on this exact workload was made, so this does
not establish an end-to-end before/after speedup. Plan 071 separately measured the removed
native re-encode (Square median 943.30 → 15.56 ms under the same release).

## Quality and orientation

The JPEG recovered from **actual Bluetooth writes** is exactly the prior Python reference:

- 800×800, 102,303 bytes, selected quality 76, Square transport flip false.
- JPEG SHA-256 `1354cc449d9903ef44a15c09f9e75e35484af2f596df89034a3255ebed337ec8`.
- Decoded RGB SHA-256 `a7b9a07e96030e453f17d2c72f5bd99d7a01f06f1e47055f197e982bb7d262f9`.

The recovered image was decoded and shown to the user for comparison. After development, the
user confirmed the physical film was **upright, unmirrored, and free of unusual colour or detail
problems**. This is direct visual confirmation for this Square photo and saved settings; no
instrumented colour measurement, film photograph, other model print, or all-scene quality claim.
Personal image pixels and the raw Bluetooth capture are retained locally, not committed to Git.

## Next optimization: BLE transfer

The transfer dominates this run. Exact HCI attribution:

- **10.089 s** accumulated span between first and last outgoing fragment of each data chunk.
  This is transport fragment dispatch time, not isolated CPU cost or a pure RF measurement.
- **2.785 s** waiting from each chunk's final outgoing fragment through its Printer ACK;
  mean 48.85 ms, range 45.40–61.79 ms.
- **8.707 s** between ACK and next chunk send across 56 gaps, mean 155.48 ms; plus **0.158 s**
  after the last data ACK before DownloadEnd. The configured minimum is 150 ms per chunk,
  8.550 s total; actual scheduling adds small overhead.
- DownloadStart/DownloadEnd ACKs and small dispatch gaps account for the remainder.

A read-only BlueZ query after printing reported the write characteristic MTU **247**, flags
`write-without-response` and `write`, and WriteAcquired false. Current core fragments are fixed
at **182 bytes**. A full Square packet is 1,819 bytes, requiring **10** current writes; an
ATT value budget of 244 bytes would require **8**. The negotiated MTU is exposed by the
[BlueZ 5.82 GATT API](https://raw.githubusercontent.com/bluez/bluez/5.82/doc/org.bluez.GattCharacteristic.rst).
The installed btleplug 0.11.8 public Peripheral API has no MTU getter.

**First candidate:** measure a transport path that respects negotiated MTU and preserves
per-model fallback, byte identity, ACK ordering, timeout/cancellation and reconnect behavior.
Potentially fewer writes address the largest non-sleep span. A larger negotiated ATT MTU does
**not** prove the Printer's application firmware accepts larger Instax fragments; that requires
controlled validation before changing production. A Linux acquired-write path is another option,
but must own/close its descriptor and re-acquire after reconnect, per the same upstream API.
No acquired write or larger-fragment send was attempted in this audit.

**Second candidate:** benchmark a smaller post-ACK delay independently, keeping one command in
flight and testing multiple photos/models and recovery. This could reduce the measured 8.9-second
wait budget; one success at 150 ms gives no evidence that a shorter delay is reliable. No delay
was changed. HIF source opening remains the next CPU bottleneck at 5.22 seconds. Cached edits
already bypass that decode. Optional LED handling is not a meaningful target on this run because
its ACK arrived in 26 ms. Review/render/Printer lookup contributes another 2.06 seconds, including
the deliberately retained one-second review.

## Final state and evidence

Bridge/manager remained active, PIDs 13129/13127, NRestarts=0; FTP stayed listening, dark idle
returned to powersave 600 MHz / GPIO24 low, no throttling. Printer status stayed fresh at film 3
through 08:28:13 EDT. At 08:28:23 it became unavailable and then stopped advertising; the cause
was not observed, and this audit does not establish indefinite Printer uptime. The Bridge kept
its normal saved-Printer reconnect/search behavior. No service was restarted.

The temporary monitor/process, root-owned trace/probes and duplicate benchmark upload were
removed from the Pi after completion. The original HIF is retained. Production source/artifacts
are unchanged. [Sanitized timing, transactions, hashes and verification](../assets/bridge-audit-072/measurements.json).
