# Bridge Bluetooth chunk pacing

## Scope

Optimize the Square Printer's post-ACK 150 ms chunk delay using no-film evidence on the Pi.
Three subagents own implementation, independent tests and adversarial review; root controls
hardware benchmarks and deployment. Work starts from clean 096c7ca, native a24b8b7.

Image bytes, model geometry/orientation, chunk sizes, 236-byte production fragments, ACK ordering,
and pre-execute waits remain unchanged. Other models and platforms retain their existing pacing.
The final chunk keeps its model settling delay before DownloadEnd. SD caching does not change
these Bluetooth waits.

## Safety audit

Current Data ACK matching checks only the opcode, although the observed Square reply echoes a
32-bit chunk index. The correction enforces an exact reported index and rejects malformed indexed
replies for Square only, where the echoed index is verified. Other models keep their response-tail
compatibility until hardware evidence supports a stricter interpretation. Exact one-byte legacy status replies remain compatible. They cannot authorize faster
pacing; the baseline is retained after a legacy reply. Stale/future ACKs share the transaction's
original deadline, without sending the chunk again.

Any accelerated transfer failure must require a fresh connection and conservative pacing for
future jobs. No uncertain image is replayed. A failure before acceleration starts must not falsely
disable faster pacing. Transfer cancellation and failures around End/execute need explicit review.

## Benchmark design

Real hardware: Pi Zero 2 W, ST7789, X306 2300 mAh, Debian 13.2 / Linux 6.12.47+rpt-rpi-v8,
Python 3.13.5 / BlueZ 5.82 / Bridge 0.1.17, Instax Square INSTAX-52006924.
Use the previous DSC02825.jpeg at saved Auto fit / Vivid saturation 1.5 / neutral Correction.
Prepared Square JPEG is 102,846 bytes / 800×800 / quality 87; SHA-256
`867ca28e128bd60149a33d719646ab649c12d4d45d62e0b104e4ec1dda32f878`.

One connection, fixed 236-byte fragments, two reversed-order rounds of intermediate delays
150 / 100 / 75 / 50 / 25 / 0 ms. Only a matching indexed ACK authorizes the next shorter wait.
Final settling remains 150 ms. DownloadStart → 57 Data ACKs → DownloadEnd → DownloadCancel,
with exact ACK checks and no PrintImage, LED, reset or shutdown command. CPU is sampled at
1000 MHz; normal power/service behavior is restored after each trial. Compare before/after film
and history, reconstruct the outgoing JPEG from HCI and verify checksums, padding and indexes.

Follow with fresh-connection comparisons of the selected policy and baseline, then exercise the
installed production transfer loop without executing a print. Final reconnect and dark 600 MHz
health checks must pass. No-film evidence proves outbound byte identity and protocol acceptance;
it does not independently measure developed-film appearance, mechanical execution, other models,
battery energy or real camera Wi-Fi airtime.

## Validation gate

Mock/paused-time tests cover every model's baseline, held/stale/indexed/legacy ACKs, operation
serialization, exact prepared bytes/flip/padding, final settling and pre-execute waits, failure and
cancellation, bounded fallback, no replay and no-film diagnostic command restrictions.
Run affected Rust gates, header drift if needed, App logic checks and strict docs. Record the
selected timing, sample size, independent review, clean native provenance and installed hardware
state before declaring completion. Personal pixels and raw Bluetooth captures stay out of Git.

## Initial offline implementation status

During initial offline preparation, production preferred delay remained **150 ms** pending
hardware measurements. The new no-film
helper shares the production transfer loop, hardcodes print option 0, checks Cancel ACK and
never calls LED or PrintImage. The diagnostic wrapper also rejects actuator packets.

A full-transfer guard covers Start/Data/End/handoff/execute and cancellation during chunk waits.
Interrupted transfers require reset; after an accelerated wait, uncertain errors restore baseline
pacing for future jobs in a bounded 128-device cache. Fragment and pacing fallback are separate.
Known NoFilm/CoverOpen/LowBattery errors require reset without falsely penalizing pacing; busy,
unknown rejection and transport uncertainty remain conservative. The first selected shorter wait
is marked before await, and the final settling delay is excluded.

Three subagents completed implementation, independent tests and review. No unresolved P1/P2
issue in this passive 150 ms state. **278 Rust workspace tests**, build, fmt, Clippy, committed
FFI header drift and strict docs passed. All **52** targeted mock tests also passed on real Pi
arm64, including five Linux-specific transport cases. Hardware benchmark, shorter-delay selection and final
firmware deployment remain pending because the Printer is unavailable/not advertising. The Pi
remains reachable and its existing services are active. No film consumed in this task.


## Hardware selection

After Printer discovery resumed, all 12 sweep transfers completed successfully. Two reversed-order
samples per intermediate delay, fixed 236-byte fragments and final 150 ms settle:

| Intermediate gap | Mean download/end/cancel |
|---|---:|
| 150 ms | 23.403 s |
| 100 ms | 19.296 s |
| 75 ms | 17.376 s |
| 50 ms | 15.704 s |
| 25 ms | 14.947 s |
| 0 ms | 13.139 s |

The first 150 ms sample was 25.281 s versus 21.524 s on its repeat; it is not a representative
warm baseline. A fresh connection with 25/150 then reversed 150/25 gave **22.266 s** at 150 ms
and **15.349 s** at 25 ms: **6.918 s / 31.1% less transfer time**. Four complete samples;
this excludes camera upload, processing/review, pre-execute and mechanical printing.

Select **25 ms** to retain intermediate settling margin even though zero delay was accepted.
Only Square/Linux/236-byte/indexed-ACK connections use it; fallback and unverified contexts keep
150 ms. Final settle 150 ms and pre-execute 1000 ms remain unchanged. No film used. All 16
transfers reconstructed the identical JPEG/RGB hashes, ordered indices, zero padding and checksums.
There were 912 indexed Data ACKs, exact End/Cancel ACKs and zero actuator commands. Film stayed
1 and history stayed 67; both trials disconnected successfully. All clock samples were 1000 MHz
with no throttling. This establishes protocol acceptance on this Square/Pi, not internal stored
pixels, developed-film quality, mechanical timing, other models or battery runtime.

Independent adversarial review decoded the sweep separately and confirmed the evidence. The
selected constant still passes model/platform/fragment/legacy/failure gating tests. Shared
production-loop and installed-firmware checks follow before completion.


## Shared production transfer check

Selected 25 ms compiled code exercised the actual `send_image_data` loop via the strict no-film
helper. Two successful runs took **14.875 / 14.850 s**; each reported exactly 56×25 ms waits and
one final 150 ms wait, 236-byte payload, 57 indexed ACKs, identical JPEG/RGB/padding/checksums,
checked End/Cancel and no actuator commands. Film 1/history 67 unchanged; clean disconnect,
1000 MHz, no throttling. This validates the shared transfer path while avoiding PrintImage.

An earlier production-probe attempt failed before model detection/Data with `Not connected`.
HCI shows connection establishment followed by reason 0x3e; no host Disconnect or image packets.
Normal Bridge recovered automatically. The harness now explicitly closes/verifies the prior link
before a fresh probe; this is controlled handoff, not proof that an old disconnect timer caused
the event. The failed setup is retained separately and excluded from timing means.
