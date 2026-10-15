# Python startup and imports

## Scope and implementation

Keep the native Bridge startup focused on LCD, camera receive and automatic Printer reconnect.
Shared Printer types/errors now live in `ble/types.py`; image contracts, settings and pure
cache metadata live in `imaging/models.py`. Existing public imports re-export the same objects,
including worker serialization and exception identities. Native ABI, protocol/image algorithms,
CPU tiers, configuration and service ordering are unchanged.

Diagnostic Bleak imports occur on first use off the event loop. Photo transforms load in the
existing preparation process or native/metadata/preview thread. The lightweight image worker
still imports at startup. The Post editor awaits an off-loop processing import before entering
its first rendered frame, with stale-state and cancellation guards. No startup prewarm is added.

## Adversarial review and source validation

Three subagents investigated, implemented and independently reviewed the change. Review found
an import-lock wait during cleanup after cancelled first use, and a synchronous cold import on
the first Post slider render. Both were fixed. Independent final review passed 45 focused tests,
verified unchanged algorithm bodies and accepted the source. The serial input queue still waits
for the first editor import to finish; tests demonstrate event-loop responsiveness and stale
state rejection, not consumption of queued buttons during that wait.

The full Bridge suite passes **2,527 tests**, with eight expected Mac GPIO fallback warnings.
Ruff lint/format (164 files), strict mypy (70 source files) and whitespace checks pass.

## Predeployment Pi comparisons

Pi Zero 2 W Rev 1.0, ST7789 240×240 framebuffer, X3062300mAh; Debian13.2,
kernel6.12.47+rpt-rpi-v8, Python3.13.5, BlueZ5.82. Installed baseline44e6cb4;
candidate frozen source staged in a temporary tree using the installed interpreter/dependencies.
Normal Bridge service retained, no CPU policy mutation or Printer operation in these probes.

Counterbalanced fresh-process app imports, two warmups then three samples per tree, precompiled
bytecode/warm filesystem cache, all observed600MHz/powersave: baseline median **2.108s**
(range2.078–2.117), candidate **2.026s** (2.019–2.108), about82ms lower. This modest result
measures app imports only, not cold power-on or total connected time. Required Pillow LCD and
D-Bus imports remain; diagnostic and pixel-processing modules are absent on fresh native import.

Actual Pi image worker comparison uses a retained Sony DSC02821.HIF and an asymmetric EXIF6 JPEG
fixture. Square JPEG0.516→0.523s, HIF5.752→5.434s, Mini Link3 JPEG0.435→0.456s and Wide
JPEG0.623→0.655s; single observations, no general processing-speed claim. Every output JPEG is
byte-identical, with identical dimensions, fit, quality and model-specific flip metadata.
No physical film or end-to-end camera dispatch was used. Native transport is unchanged.

An initial temporary BSD archive contained AppleDouble metadata and was replaced with a clean
source-only archive before accepted runs. An initial pair of overlapping import/image probes
was rejected for timing and rerun sequentially. Neither changed production source/service.

## Installed acceptance

Clean source **079af5a** is installed. Baseline→installed kernel-monotonic reboot measurements:
LCD13.822→13.665s, FTP13.810→13.652s, core13.835→13.676s, fresh Printer20.484→18.962s.
No button action before connection; film10→10. Process launch→boot marker3.340→3.233s.
Single reboots are observations, not a general connected-time speedup or proof that imports
caused the entire1.522s difference. Advertising/bond paths differ: candidate retained guarded
startup reset (~0.8s), while baseline discovered later. Firmware startup is excluded.

Actual Pi offscreen rendering produced92 exact RGB matches covering all modes and3 Post editors,
English/Chinese and light/dark. Live awake framebuffer115200bytes/148distinctRGB565 values,
1GHz/performance/backlight high; later normal idle600MHz/powersave/backlight low/cleared frame.
Physical panel quality and button contacts were not observed. Full local UI/input/lock regressions
pass; this round changes no input or renderer algorithm.

External BlueZ Disconnect→fresh automatic status passed **12.543s** while screen-off.
All23samples retained PID482/600MHz/powersave/GPIO24low/FTP220+200; film10→10. Samples start
2.590s after dispatch because Disconnect initially blocks. One absent first scan was logged at
INFO; the existing prompt retry then connected successfully, with no manual Reconnect or warning.
Normal screen-off idle is verified, not introspection of the internal manual-lock flag.

An isolated installed production FTP service received a JPEG byte-for-byte into ReceivedImage
queue, STOR226/NOOP200. Temporary directory/credentials/highport and no consumer/native backend
prevent printing. Normal port21 retained; physical camera and normal print dispatch not tested.

Bridge482/manager640 active, zero automatic restarts; Printer connected/fresh, throttle0x0,
network/Bluetooth/backup socket active. All17 changed source hashes match the benchmark archive
and079af5a; systemd unit and native FFI remain unchanged. Complete current-boot Bridge PID
journal101records has no warning/error matches. Broader Bridge/manager/Bluetooth review124records
retains BlueZ directory-mode and deliberate-disconnect notices, plus manager hotspot bind pending
which resolves1.006s later. No whole-system warning-free claim. Temporary probe resources cleaned.

Three subagents and final independent evidence review cover source, output equality and live
acceptance. Evidence: [plan097 measurements](../assets/bridge-audit-097/README.md).
No Printer image-transfer, print or actuator command; no film used.
