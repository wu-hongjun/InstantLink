# Bridge live runtime acceptance

Deploy plan075, review complete available service/kernel journals, and validate installed
lock/unlock, printing and automatic recovery on Pi Zero2W / ST7789 / X306 / Instax Square.

## Live finding: inactive BlueZ records

The fresh boot retains the saved Printer's name, UUIDs and bond, but Connected=false and no
RSSI property. Native discovery accepts the cached name immediately and attempts connection:
30-second reply timeout followed by In Progress. Cancelling a genuinely long call during
deployment hit the old runtime's five-second cleanup deadline. Plan075's completed-error
correction does not claim to fix a still-running native connection attempt.

On Linux, exclude a candidate with neither RSSI nor a confirmed connected link. Keep already
connected devices usable without advertisements. Bound connected-state queries by one shared
250ms budget per collection, rather than paying a new timeout for every cached Printer.
Other platforms and image/packet/pacing behavior stay unchanged. RSSI is scan evidence, not
a guarantee of current liveness; stale RSSI after prior discovery remains a limitation.

## Hardware validation

Use a temporary root/ib-only Unix socket observer around the installed runtime. Send abstract
button events through the same action queue as GPIO; use the actual LCD/framebuffer, CPU helper,
FTP, networking, FFI and saved settings. Record this automation boundary: it does not test the
electrical switch contacts. Restore the normal service afterward and remove the observer.

Check same-button unlock including different GPIO identities sharing Select, blank-frame
regression, ten-second abandonment and CPU return to600MHz. Upload DSC02825.jpeg once through
production FTP for one authorized physical print; no uncertain retry. Check film/history and
captured JPEG bytes, expected orientation, ACKs, CPU boost and terminal UI state. Recover a
controlled disconnected link automatically while locked and retain service/FTP/network health.
Separate deployment/test restarts from spontaneous failures and historical faults.

## Live finding: startup bond recovery

Repeated service-discovery failures after deployment exposed a missed online→offline edge:
BlueZ retains the Printer bond across Bridge restarts, while an Instax power-off can clear
its key. Check the existing `reset_bond_if_disconnected` guard once when a status polling
generation starts, after backend readiness and before its first fetch. Connected identities
are preserved; selection is retained. Superseded generations do not fetch after the check,
and cancellation propagates through owned cleanup. Three regression cases fail before the
fix. This startup action is logged at INFO with its actual reason.

The user-selected validation photo changed to DSC02832.jpeg because the earlier source was
no longer present. Preserve the original and saved processing settings.

The same live attempt showed reactive bond removal racing a later status connect:
`bluetoothctl remove` timed out while the poll entered discovery again. Polls now await
active rebond recovery before their startup guard or another fetch, using shielded ownership
because recovery may replace the polling generation. A regression test verifies the wait
and that cancelling a poll does not cancel the recovery task.

## Live finding: down interface with retained IPv4

A locked wlan0-down fault left 192.168.8.1 assigned, and the address-only health snapshot
continued reporting receive-ready indefinitely. Recovery did not run; Printer stayed
connected. Restore wlan0 explicitly after this failed probe. The shared bounded address
snapshot now excludes interfaces whose explicit Linux flags omit UP. This also avoids
Bonjour advertising an administratively down endpoint. Do not require LOWER_UP/carrier or
operstate=UP: dormant AP/USB interfaces must remain available. Five cases cover down and
admin-up/dormant/unknown state; the two down cases fail before the fix. No additional poll,
subprocess, public field or sync wire-contract change is needed.

## Hardware results and remaining cost

- GPIO-equivalent queue events on the actual ST7789 framebuffer passed prompt/nonblank frame,
  button-identity reset, three same-button unlock and 10-second abandonment. Timeout/lock
  returned to 600MHz; awake prompt/unlock ran at 1000MHz. No electrical contacts actuated.
- One production FTP print of DSC02832.jpeg passed, film1→0, history67→68 on later fresh
  connection. Initial post-print history remained67 while the Printer finished its own work.
  Exactly one PrintImage, 58 ordered indexed ACKs and exact 104,552-byte/800×800/quality88 JPEG
  and RGB reference hashes, Square flip=false. Captured image reviewed upright; developed
  film not inspected. 19.779s FTP-start→Bridge completion; processing1.844s, download15.238s,
  native handoff→completion16.340s. Same-Pi FTP excludes camera airtime and mechanical/development
  time. All65 sampled job clocks were1000MHz, throttle0x0; locked600MHz resumed afterward.
- Forced authoritative BlueZ disconnect recovered automatically in44.340s with unchanged
  Bridge PID3981, fresh status and physical Connected=true. Screen stayed locked600MHz.
  Genuine warnings caused by the injected lost link are recorded, not suppressed.
- The retained-IP wlan0 fault failed before the network fix; the interface was manually
  restored. With the fix, a second outage recovered via the normal hotspot helper in32.706s,
  restoring AP/readiness while locked600MHz. This repeat had the Printer offline; connected
  Printer retention during the new recovery still requires a powered Printer. No camera
  association/airtime measurement.
- A30s dark/offline sample used3.1 process CPU seconds (10.33% of one core at600MHz). Native
  GPIO polling was the largest identified thread (6.9% lifetime CPU); a separate1s strace
  showed ppoll on8GPIO-line FDs with mostly500µs timeouts. Python GPIO held threads and Rust
  workers were low. No dependency/alert timer changed: that needs electrical input latency,
  bounce and held-button validation. This is not an energy measurement or before/after claim.

Local gates: Bridge1551, Rust282 including doctest, App156; Ruff/strict mypy65 files, touched
format, Rust build/fmt/Clippy/header drift, strict docs and normal hooks passed. Pi runtime
has no pytest installed; no test dependency was added. Native clean dedfdb2 SHA and runtime
clean8bbbd88 provenance are saved in `docs/assets/bridge-audit-076/`. Printing used811d51f;
subsequent8bbbd88 changes only network snapshot filtering and retain identical print/native
code. No additional physical print is needed; the Printer now has no film.

## Normal service restoration

Removed the root/ib-only observer socket, owned runtime drop-in, scripts, duplicate audit
source/incoming photo and raw capture. Original user photos and saved config remain. Normal
ExecStart is `/opt/InstantLinkBridge/.venv/bin/instantlink-bridge --config
/etc/InstantLinkBridge/config.toml`. Final normal PIDs6248/5125 active, NRestarts0, dark
GPIO24low/600MHz,45.084°C,throttle0x0,FTP220/200, USB/hotspot up, working caches0. Printer
is offline at this final sample, so combined Wi-Fi/connected-Printer repetition remains
pending the power-on question. Earlier physical print and locked Bluetooth recovery passed.
Raw journals remain private; the final complete available current boot was reviewed again.

The final kernel review also found23brcmfmac vendor-IE -52 records around Bridge startup/AP
reconfiguration and deliberate interface-down, plus one hci_conn_timeout WARN at00:23:43UTC
(mono1553.025s) during the earlier failing runtime before startup-bond/rebond-wait fixes.
No repeat HCI WARN occurred in subsequent captured checks, but its kernel root cause is not
established or claimed fixed. AP/FTP and later Printer operation recovered. These are recorded
as driver/firmware maintenance follow-ups; no OS/kernel upgrade was performed in this audit.

## Connected Wi-Fi acceptance completed, 2026-10-12

The user powered the Printer on. Installed clean cee3755 (documentation successor to8bbbd88,
identical runtime/native code) passed the final wlan0-down/retained-IP repetition in32.672s.
Across31samples the real Bridge stayed locked600MHz, PID7032 unchanged, and authoritative
BlueZ Connected=true. Four successful status observations, maximum status age9.543s, prove
continued communication during the outage/recovery. Film0→0/history68→68; no photo upload
or print command requested. The normal hotspot helper alone restored AP and receive readiness.
No camera association/airtime test. This completes the pending combined check above.

The temporary observer/socket/drop-in was removed again. Normal ExecStart/PID7530 returned
and automatically connected, with fresh film0 status, manager PID5125 active/NRestarts0.
Record the final dark-idle/FTP/network health separately after its normal idle timeout.

Final normal-service health after the connected repetition: PIDs7530/5125 active/NRestarts0,
600MHz/powersave/GPIO24low,45.084°C/throttle0x0,FTP220/200, USB/hotspot up, working caches0,
Printer Connected=true. Native hash unchanged. Observer/drop-in/socket and owned scripts
removed. The audit records changed in Git; production source/native code did not change,
so installed cee3755 remains the validated runtime.
