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


## Clean firmware deployment

Selected source **f574445968e963ae35231d64d5f784ac1f5a5b28** was committed, pushed and deployed
using the standard arm64 artifact build and Bridge deploy script. The manifest records a clean
worktree and locked release build; the installed FFI SHA-256 matches
`b601ec6a8b14138617ebbae5e5c74b892bb461ee2d2747dbfc6ed181f253bacb`.

Selected code passed Rust **278** workspace tests, all **52** targeted arm64 tests on the real Pi,
format/Clippy/header checks and strict docs. The normal source-commit hook also passed Bridge
**1,524** tests, lint and mypy. Three subagents implemented, tested and independently reviewed.

Initial installed health: both services active, NRestarts 0, correct USB/hotspot addresses,
FTP 220 / NOOP 200, no throttle or working caches. After the normal 60-second idle timeout,
the screen was off (GPIO24 low) and CPU was **600 MHz / powersave**, with FTP/Wi-Fi still ready.
The Printer had stopped advertising during the build, so these initial health records explicitly
show it disconnected and do not establish post-deployment Printer reconnect.

The first installed probe stopped before discovery/image commands because its temporary harness
required a cached BlueZ device. An absent cache now permits fresh discovery; a connected cache
still prevents starting a fresh probe. No production-source change or film consumption resulted.
At this stage, the post-deploy shared-core probe and installed FFI reconnect checks awaited
the next Printer power-on.


## Final installed validation after Printer power-on

The shared-core no-film probe rebuilt from clean **f574445** passed two post-deploy transfers:
**14.950 / 15.104 s**, 236-byte payload and exactly 56×25 ms plus final150 ms waits each.
An independent decoder verified 114 exact indexed ACKs, unchanged canonical JPEG/RGB hashes,
ordered requests/replies, padding/checksums and two successful End/Cancel pairs. Zero actuator
commands, film1/history67 unchanged, all sampled CPU clocks1000MHz and throttle0x0.

The actual installed FFI separately passed two status/disconnect/fresh-reconnect cycles:
Square, MTU247/payload236/conservativefalse, film1/history67, return code0 and authoritative
closed state in **2.769 / 2.206 s**. Independent HCI decoding confirmed two physical Disconnect
Complete events and only support-info commands, with no Download/PrintImage/LED/reset/shutdown.
The shared-core probe exercises the installed source's transfer loop; it does not call the FFI
print API. No new physical-film appearance or mechanical print timing was measured.

The normal Bridge automatically reconnected after probe restoration. Final idle state:
**600 MHz / powersave**, screen off/GPIO24 low, Printer connected, fresh film1/battery35 status
following the powersave transition. Both services active with unchanged PIDs/NRestarts0,
Wi-Fi/USB addresses correct, FTP220/NOOP200, throttle0x0 and zero working caches. Runtime docs
commit61925ba and native sourcef574445 are both clean; installed FFI hash matches the official
manifest. The final independent adversarial review found no unresolved issue.

Sanitized evidence is in `docs/assets/bridge-audit-074/`. Temporary test binaries, duplicate
photo uploads and raw captures are removed after review; the user's original DSC02825.jpeg
is retained. The Bridge remains running normally with the selected 25 ms policy.


## Extended idle observation

After completing the connected screen-off check, normal status polling continued every ten
seconds through **14:47:03**. The first unavailable status was **14:47:13**, approximately
299 seconds after reconnect and over three minutes after the 600 MHz transition. Services and
Bluetooth daemon PIDs remained unchanged; documentation-only deployment did not restart them.
Latest health still verifies powersave600MHz, screen off, Wi-Fi/FTP ready, NRestarts0, no throttle
or working caches, with the Printer offline.

This timing is consistent with the Square's documented five-minute idle auto-off
([Fujifilm manual](https://instax.com/square_link/assets/pdf/manual_naen.pdf)); the
[official FAQ](https://www.instax.com/square_link/en/support/) documents its automatic power-off
toggle. The user's physical power-light confirmation remains pending, so actual power-off is
not asserted. Independent review found no reason to invalidate completed transfer/reconnect
checks: selected pacing affects image DATA transfers, while idle support-info handling is
unchanged. Bond-cache reset occurred after the Printer disappeared. No pacing rollback or
Printer power-setting change was made. Do not infer indefinite idle availability from these
checks.
