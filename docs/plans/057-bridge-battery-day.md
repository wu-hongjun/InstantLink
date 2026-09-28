# 057 — Bridge battery day and reconnect behavior

## Goal and hardware

The portable Bridge now uses one 2300 mAh, nominal 3.7 V 18650 cell in the
SupTronics/Geekworm X306. Keep camera FTP and automatic Printer reconnect ready
throughout a shoot while removing work that does not improve that experience.
KEY2 on the home surface locks the physical LCD; Print/Sync Mode moves to the
main Settings page.

The installed battery directly powers the Bridge. The X306 has no host-readable
current, voltage, state-of-charge, or charge-state interface. Its LEDs provide
coarse battery indication. Software CPU and thermal measurements are **not**
power measurements. A full-charge-to-cutoff discharge run is needed for real
runtime, and any estimate must state its workload and initial charge.

The cell's nominal energy is `2.3 Ah × 3.7 V = 8.51 Wh`. A 24-hour target permits
an average draw of just `0.355 W` at the cell, before X306 conversion loss. The
Raspberry Pi documentation lists 350 mA typical bare-board current for the Zero
2 W at 5 V (about 1.75 W). This figure alone implies under 4.9 hours before
UPS, Wi-Fi, BLE, LCD, and workload losses. It is a reference figure, not a
measurement of this Bridge. A continuously awake, discoverable Pi with this
single cell should not be described as a 24-hour product until a discharge test
proves it. X306 hardware poweroff has very low standby draw, but an off Pi cannot
receive FTP or reconnect automatically when a camera or Printer turns on.

Sources: [Raspberry Pi hardware power table](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html),
[Geekworm X306 specification](https://wiki.geekworm.com/X306).

## Live baseline, 2026-09-27

The Pi is `riverps-rpi-zero-2w`, Bridge 0.1.17, Debian 13, Zero 2 W, X306,
physical LCD, Bridge Wi-Fi hotspot, and Instax Square selected but powered off.
USB admin was attached to the Mac, so these are **mains-powered activity samples**,
not a battery discharge. The Pi clock was 16 days behind the host; samples use
boot ID and monotonic uptime to establish order. The LCD backlight was off
(`bl_power=4`) during all samples.

| Profile | Search period | Aggregate CPU busy | Notes |
| --- | ---: | ---: | --- |
| Previous device config | 5 s | 8.75% mean, four 5 s intervals | Bridge 13–15%, D-Bus 7–11%, Bluetooth 6–9% of one core; effectively continuous BLE search |
| Battery profile | 30 s | 3.67% mean, seventeen 5 s intervals | 5 s scans with idle gaps; CPU dropped to 600 MHz between scans; mean SoC temperature 50.6 °C |
| Battery profile, development services stopped | 30 s | 3.93% mean, seventeen 5 s intervals | mean SoC temperature 49.5 °C; available RAM about 285 MB |
| Plus 5 s dark-screen network status polling | 30 s | 3.42% mean, seventeen 5 s intervals | mean SoC temperature 48.6 °C; Bridge process 7.6% of one core versus 8.7% in prior row |

These CPU means are short observations over different phases of the scan cycle;
the small differences among the 30-second rows are within this sampling
variation. Stopping development services is a memory/boot improvement here;
the dark-screen poll change removes four out of five network probes, but the
short CPU sample does not establish a battery-life gain.
They show that the old search loop was substantial avoidable work, but do not
establish a percentage battery saving. `bridge/scripts/benchmark-power.py` records
boot ID, uptime, CPU, process activity, temperature, memory, Wi-Fi counters, and
backlight state as low-overhead JSONL.

The on-device `[printer].search_interval_s` was changed from 5 to 30, with a
backup at `/etc/InstantLinkBridge/config.toml.bak-battery-baseline`. The code
default is also 30 seconds; the existing Settings choice of 5/15/30/60 seconds
remains available. Automatic scanning continues while the Printer is offline.
The user can choose the 5-second option when immediate reconnect is worth the
continuous radio activity. FTP preflight waits for a fresh ready Printer status
before accepting an upload in Print mode; the periodic status scan restores that
readiness after the Printer turns on.

The device's production boot diet was applied over the USB admin link:
`tailscaled`, a GitHub Actions runner, and the user-level `rpi-connect` service
were stopped and disabled. The safe apt/maintenance units were also disabled.
Available RAM rose from about 197 to 281 MB; swap use fell from 67 to 45 MB.
USB SSH, hotspot, FTP, Bluetooth, and Bridge services remained active. This is
reversible and does not change the source build.

## UX and power behavior

- KEY2 on a normal home/status surface turns the LCD backlight off immediately.
  Any next physical or virtual key wakes the LCD and is consumed, so it cannot
  accidentally open Settings or change an option.
- A deliberate lock persists through FTP, Printer status, and idle-timer activity.
  The Bridge continues receiving uploads and reconnecting while locked.
- While the LCD is off, the controller skips physical framebuffer renders;
  virtual LCD snapshots still use the same state machine and renderer on demand.
- The network-status watcher checks every 5 seconds while the LCD is off
  instead of running two `ip` subprocesses every second. FTP listeners and
  incoming-upload events stay live; the 1-second status cadence resumes while
  the screen is visible.
- Settings > Mode is the one place to choose Print or Sync. The QR pairing action
  remains on Settings > Network. KEY2 is still Back/Cancel inside menus and
  print previews.

## Discharge test and acceptance gates

1. Fully charge the installed 2300 mAh cell using the device's existing power
   wiring until its charge indicator shows full. Record the battery make/model,
   X306 revision, room temperature, and workload. Disconnect external charging
   power at the start so the battery is the Bridge's only energy source; do not
   assume a USB connection is data-only.
2. Start the sampler as a transient systemd service before disconnecting power:
   `sudo systemd-run --unit=instantlink-battery-run /usr/bin/python3
   /opt/InstantLinkBridge/scripts/benchmark-power.py --interval 60 --output
   /var/lib/InstantLinkBridge/battery-run.jsonl`. This logger is already running
   on the current Bridge. Mark the external-power disconnect time. Each sample
   is flushed to persistent storage. Use monotonic uptime from one boot to
   calculate elapsed time even if the Pi's wall clock drifts.
3. For the first full cycle, leave the hotspot on, Printer off, screen locked,
   and do not send camera uploads. Let the Bridge run until the battery hardware
   cuts power. A realistic shoot with camera FTP and Printer on requires a
   separate full charge and full cycle; record prints and idle gaps for that run.
   These are different battery claims and must not be conflated.
4. After cutoff, reconnect charging power and read the saved JSONL. Confirm the
   boot ID changed, then compare the last same-boot uptime with the sample
   nearest the marked disconnect time. The last durable sample is a lower bound;
   if the logger remained active until hardware cutoff, the 60-second interval
   bounds the cutoff to before the next expected sample. The X306 has no software
   low-battery shutdown signal, so the Bridge may stop abruptly.
5. With the Printer initially off, turn it on and measure time from its power
   button to a successful `ui.printer_status` log and READY screen. Repeat with
   the camera joining the hotspot and sending a photo. Verify no manual
   pairing, service restart, or lost queued print is needed.

## Further work after the discharge result

- If reconnect exceeds the 30-second scan cadence plus connection time, inspect
  BlueZ bond recovery and the Rust FFI scan path before increasing scan duty.
- Measure a connected, idle Printer with 10/30-second keepalive intervals before
  changing the default; a longer interval is useful only if it preserves the
  link and printer wakefulness.
- If a true 24-hour always-ready target remains, change the energy source or
  add external wake/power-control hardware. Software-only idle work cannot
  make a Zero 2 W hotspot and BLE appliance average below the cell's 0.355 W
  day budget based on the published bare-board power figure.
