# Current Bridge Context

## Reliable wake and three-press unlock, 2026-09-30

Clean runtime `fb1f27e` is deployed on the Raspberry Pi Zero 2 W Rev 1.0 / Waveshare
240×240 ST7789 LCD HAT / X306 2300 mAh cell, Debian 13.2, kernel 6.12.47+rpt-rpi-v8,
Python 3.13.5 and BlueZ 5.82. Bridge 0.1.17 restarted at 13:47 EDT after the smoke check.
The default-enabled guard is live: **Settings → System → Unlock: 3 presses**. The App also
exposes the toggle. KEY3 remains Reconnect when the saved Printer is offline, and Post when ready.

- Fixed blank wake caused by black framebuffer pixels plus an unchanged cached UI snapshot.
  The retained frame is restored before the backlight comes on, and wake forces a current redraw.
- First press shows one filled circle and warms the CPU; second shows two; third restores the
  latest state. Inputs are consumed. An incomplete sequence expires after 10 seconds.
- Real framebuffer/backlight smoke passed under the runtime `ib` account with the Bridge service
  temporarily stopped. Tests verified byte-for-byte frame restoration, visible prompts,
  `bl_power` 4→0, same-key and mixed-key sequences, and a newer synthetic error state appearing
  on the third press. One-press opt-out and automatic screen-off wake also passed.
- Actual governor checks recorded locked `powersave` at 600 MHz, first-press `performance` at
  1000 MHz, timeout back to 600 MHz, and opt-out wake at 1000 MHz. The service was restarted
  even if the smoke failed. No film was sent and no production photo/config values were changed.
- Bridge, manager, Bluetooth and NetworkManager are active, Bridge `NRestarts=0`, throttling
  `0x0`; hotspot FTP greeting and NOOP passed. The runtime automatically returned to backlight
  off after the check. The deployed manifest records `dirty=false` and source `fb1f27e`.
- Final checks: **1,241 Bridge tests**, **154 App tests**, Ruff, touched-file formatting,
  strict mypy (65 source files) and strict MkDocs. New toggle strings cover all 12 App locales;
  the global localization checker retains its previously verified baseline gaps.

Frames in plan 061 are Pi-rendered synthetic states. Physical GPIO press/hold confirmation,
Sony a7C II upload, Instax Square power-cycle/film checks and the 16-hour discharge remain
unverified. Shared controller tests cover busy/error FTP guards during unlocking; the overlay
does not replace operational Printer/photo state.

## Post processing and interface implementation, 2026-09-30

Plan 060 implements the plan 059 audit. KEY3 is **Post** on ready Print home, with separate
Looks and persistent Printer Correction. New correction defaults to zero; existing creative
adjustments are preserved. A user choice about moving the live +50 saturation to Correction
remains pending, so the deployment will retain the current Look values.

**Deployed runtime: `10fd031`**, clean archive, Bridge 0.1.17 on Pi Zero 2 W Rev 1.0,
Debian 13.2 / kernel 6.12.47+rpt-rpi-v8 / Python 3.13.5 / BlueZ 5.82, Waveshare LCD HAT and
X306 with 2300 mAh cell. The App contract and copy were updated in `7ca015d`.

- Final gates: **1198 Bridge tests**, Ruff lint and touched-file format checks, strict mypy
  (65 source files), **152 App tests**, whitespace checks and strict MkDocs build pass.
- The localization checker has pre-existing missing/extra keys at baseline `4f6a8e7`; comparison
  found no new diagnostic lines. All introduced App strings are present in all 12 locales.
- On-Pi shared-controller smoke passed Settings without Printer, Post/Looks/Correction navigation,
  staged Correction cancellation, context Help, wake-only input, locking during a simulated print,
  and actual killable-worker preview preparation/cancellation. Real root helper transitions were
  1000/600/1000/600/1000/600 MHz. A dark manual-confirmation wait returned to powersave after
  preparation; only preparation/rebuild and accepted printing hold the boost.
- The smoke uses synthetic state and a sample JPEG, installed Pi fonts and actual CPU controls.
  It does not inject physical GPIO or send film. Its rendered frames exposed clipped instructions
  and a wide printing title; these were fixed with nine additional font-size layout tests.
- Bridge, manager, Bluetooth and NetworkManager are active; Bridge `NRestarts=0`, throttling
  `0x0`, hotspot FTP greeting/NOOP and both manager listeners verified. Runtime automatic
  screen-off entered powersave at 600 MHz with backlight off.
- Saved Printer is still Instax Square `INSTAX-52006924`; it was not advertising during checks.
  Current creative Look is Vivid with saturation +50; Correction is 0. No live image setting was
  silently reinterpreted. The user can move the compensation to Correction independently.

Physical KEY2/KEY3, Sony a7C II upload with edit/confirmation, Printer power-cycle reconnect and
film colour output are pending user smoke checks. The 16-hour discharge target remains unmeasured.
See plan 060 and `docs/assets/bridge-ux-060/validated-screens.png` for details.

## Previous verified context

**2026-09-30 performance tiers deployed and checked:** source commit `892945a` was installed
through a clean archive and the Bridge restarted successfully (`NRestarts=0`). The root-owned CPU
helper and constrained sudo rule were installed and validated. Awake/photo work uses 1000 MHz;
dark/locked idle uses `powersave` at the supported 600 MHz minimum across cores 0–3. The live
runtime automatically switched to 600 MHz with LCD backlight off (`bl_power=4`), and kept the
hotspot, FTP, manager, SSH and 30-second BLE searches operational. `throttled=0x0` throughout.
The policy controller was exercised on-device through awake → locked → boosted job → locked →
awake transitions. A fresh physical KEY2 cycle with these new tiers remains pending.

Latest recorded real print is `DSC02697.HIF` → Instax Square, logged in the earlier session as
2026-09-28: send/print 24.837 s (prior reference 24.03 s), prepared preview reused. Upload took
11.835 s for an 11.26 MB file, compared with 7.56 s for the prior 5.19 MB file. The larger source
and upload account for most of the observed total-cycle difference. No reduced clock maximum
or duplicate preparation was found. Same-file preparation trials measured about 9.7 s at fixed
600 MHz and 5.7 s at fixed 1000 MHz, supporting the photo-job boost. Details and limits are in
`docs/plans/058-bridge-awake-performance.md`. The sampler now records the governor; it remains
disabled between discharge tests. The Pi's clock was resynced to the host on 2026-09-30.

Prior source deployment verified: 2026-09-28 on `riverps-rpi-zero-2w` (bridge 0.1.17,
branch `codex/bridge-battery-day`, commit `4455f53`, clean archive). This source-only deployment
updated the benchmark script and service unit without restarting the healthy Bridge runtime. The
prior runtime deployment restarted successfully with `NRestarts=0`; FTP `:21` and manager `:8742`
listen on the expected addresses.
The Pi clock was corrected from 2026-09-11 by the deployment script and resynced on 2026-09-28;
offline wall-clock timestamps drift or reset across boots. The earlier 2026-08-04 Sony a7C II
`.HIF` → Instax Square reference run is described below.

### Battery session, 2026-09-27

- The X306 now holds a **2300 mAh 18650 cell**. It has no Linux-readable current or charge gauge;
  the first near-full discharge ran overnight, but the exact unplug time is pending. The battery
  directly powers the Bridge. The protocol and evidence are in
  `docs/plans/057-bridge-battery-day.md`. The transient sampler wrote 206 one-minute records through
  00:07:08 EDT, then stopped at an unplanned reboot. The next boot had no USB carrier and ran the
  Bridge for 9 h 9 min before an abrupt stop around morning reconnection. The user observed empty
  battery LEDs and a dark LCD; the Pi nevertheless logged two physical inputs about seven minutes
  before its last journal entry. The final cutoff time is not independently confirmed. The Bridge
  recovered automatically after the midnight reset. A new opt-in persistent sampler unit was
  installed and verified on the Pi; it is disabled between tests and can be enabled for a repeat run.
- KEY2 now locks the LCD from home/status surfaces; the next key wakes it without also activating
  a UI action. The Print/Sync Mode picker is on the top Settings page. Locked screens skip physical
  framebuffer renders, and network status polling slows from 1 s to 5 s while the screen is off.
  These changes pass 1121 local Bridge tests. **Physical KEY2/backlight behavior is not yet
  hand-verified**; the Printer was off during deployment.
- The device's saved Printer search period was changed from 5 s to 30 s (prior config backup:
  `/etc/InstantLinkBridge/config.toml.bak-battery-baseline`). Automatic BLE search remains active.
  With the Printer off and the LCD dark, sampled aggregate CPU busy fell from 8.75% (5 s search,
  four 5 s intervals) to 3.67% (30 s search, seventeen 5 s intervals). This measures activity,
  **not** battery draw. The updated code also defaults new configs to 30 s and leaves 5/15/30/60
  s choices in Settings.
- After the dark-screen network watcher moved to a 5 s cadence, a further seventeen 5 s samples
  averaged 3.42% aggregate CPU busy and 48.6 °C SoC temperature. That small difference from the
  3.93% post-boot-diet sample is within short-run variation; it is not a runtime measurement.
- A powered 5-minute search-rate trial on 2026-09-28 averaged 2.67% aggregate CPU busy at a
  60-second interval, versus 2.94% across the longer 30-second overnight sample. Different trial
  conditions prevent translating this into battery savings. The live interval was restored to
  30 seconds immediately after the trial for faster Printer reconnection.
- The production boot diet disabled `tailscaled` and the OpenFilmAdvance GitHub Actions runner;
  user-level `rpi-connect` was disabled separately. USB SSH remains available. Available RAM rose
  from about 197 MB to 281 MB, and swap use fell from 67 MB to 45 MB. The live Bridge, Bluetooth,
  Wi-Fi hotspot, FTP, and manager services remained active.
- The paired Instax Square was not advertising during this session. A timed power-on reconnect,
  camera FTP upload, and full battery discharge remain the hardware gates.

Print/Sync mode behavior from commit `7a43570` was the prior baseline (2026-07-22). The iPhone
sync feature from plan 050 + UX audit 051 + virtual LCD 054-A was last exercised on-device with a
real iPhone on 2026-07-15.

This file is the fast handoff for anyone opening the bridge code after the InstantLink port. The
source of truth is the InstantLink repository under `bridge/`; the old standalone InstantBridge
Python app is legacy and should not receive new feature work.

## Product Shape

InstantLink Bridge is a Raspberry Pi appliance that receives selected camera photos over FTP,
prepares them for the detected Instax Link printer model, and prints through InstantLink's Rust
backend. The supported v1 camera path is hotspot-first:

```text
Camera FTP upload
  -> Bridge Wi-Fi SSID InstantLink-XXXX
  -> FTP 192.168.8.1:21
  -> pyftpdlib receive queue
  -> Pillow / heif-thumbnailer / rawpy image preparation
  -> InstantLink FFI
  -> Mini / Mini Link 3 / Square / Wide Link printer
```

The Pi USB gadget network is retained for admin, SSH, deployment, and diagnostics at
`192.168.7.1`. It is not a supported v1 camera FTP path. Same Wi-Fi FTP remains an advanced path
for cameras and the bridge on an existing network.

## Current Deployed State

- **Prior deployment: commit `0e1acab` on `main` (2026-08-04)**, clean tree, `--system --restart`.
  Verified on-device: `instantlink-bridge.service` and `instantlink-bridge-manager.service` both
  active with `NRestarts=0`; FTP `:21` and manager `:8742` (on both `192.168.7.1` and
  `192.168.8.1`) listening; no errors in the journal.

### Live print verified (2026-08-04) — closes prior open items

The 2026-07-22 entry recorded that "live printing, live film polling, physical-LCD observation
with a connected Printer" remained unverified because the Printer was not advertising. All three
are now confirmed on hardware:

- **Live print**: `DSC01595.HIF` (5.19 MB) uploaded over the hotspot from the a7C II, previewed on
  the physical LCD, and printed on Instax Square `INSTAX-52006924`. `bridge.print_start` →
  `bridge.print_complete` in 24.0 s; ~38.4 s from upload start to print delivered.
- **Live film polling**: `ui.printer_status film_remaining=2 battery=95 model=square` at the
  configured 10 s keepalive interval.
- **Model auto-detection**: `[printer] model = "auto"` resolved to `square` from the connected
  device.

Still unverified: a physical KEY2 mode switch, and Mini / Mini Link 3 / Wide hardware (only Square
has been exercised end-to-end).

### Plan 056 performance work (deployed 2026-08-04)

- Boot **1 min 35.8 s → 20.1 s**; the LCD boot splash now appears at **9.9 s instead of 95.8 s**.
  Root cause was `instantlink-bridge-boot-splash.service` waiting on a `dev-fb1.device` unit that
  udev never created — fixed by `bridge/udev/61-instantlink-bridge-fb1.rules`, which must be
  installed for the dependency to resolve (`provision-sd.sh`, so a `--system` deploy is required).
  Stable across three cold boots including a power cycle.
- Print path now runs the image pipeline **once per print instead of twice**: the LCD preview's
  prepared image is handed to the printer. Confirmed live by
  `instantlink.image_prepared source=preview prepare_ms=0`. `source=` is the diagnostic to check
  if a print ever feels slow — `inline` means the reuse did not apply.
- `incoming/` is now bounded by `[ftp].incoming_budget_mb` (default 512) **and** a 14-day age
  rule. It had never been pruned; the device was holding 98 MB back to May 25. First run cleared
  **98 MB → 10 MB**. Configs predating the key default to 512.
- `boot-diet.sh --production` drops tailscaled / rpi-connectd / any GitHub Actions runner (~110 MB
  of 512 MB on this unit). Deliberately **not** part of `--apply`, because on a dev unit tailscaled
  is how you reach the Pi.
- Full measurements, and what was ruled out with data (CPU governor, thermal throttling, Pillow
  build, worker overhead), are in `docs/plans/056-bridge-performance.md`.

**Local config drift on this device:** `workflow.auto_print_delay_s` was set to `5` (from `0`) and
`adjustments.sharpness` to `0` (from `5`) during the 056 measurement session. Backup of the prior
values at `/etc/InstantLinkBridge/config.toml.bak-056`. `sharpness = 5` maps to a factor of 1.05
applied at working resolution and then downscaled ~4x — it cost 1911 ms per print to do
essentially nothing visible.

- Prior Print/Sync behavior baseline: commit `7a43570` on branch `main`, delivered through a
  clean `git-archive` deployment with `dirty=false`.
  - On-device verification 2026-07-22: `instantlink-bridge.service` and
    `instantlink-bridge-manager.service` were both active with `NRestarts=0`; FTP `:21` and manager
    `:8742` were listening; `usb0` was up at `192.168.7.1/24` and Bridge Wi-Fi at
    `192.168.8.1/24`; logs contained `ftp.server_started`, `instantlink.library_loaded`, and
    `bridge.ready` with no startup errors.
  - The existing on-disk `destination = "both"` loaded as Print for backward compatibility.
    Sync/virtual-LCD `:8721` was intentionally not listening in Print mode. Pressing KEY2 switches
    to Sync and persists the new two-mode value; KEY2 switches back to Print from Sync.
  - The saved Printer was not advertising during the deploy, so live printing, live film polling,
    physical-LCD observation with a connected Printer, and a physical KEY2 mode switch remain to
    be verified. The connected-film renderer path was previously verified with a synthetic
    `Connected · Film 7/10` snapshot and a 240x240 frame on 2026-07-18.
  - Prior on-device verification 2026-06-12: LCD screen-off drives GPIO 24 LOW after the configured
    idle threshold (was previously a silent no-op because `bl_power` was `root:root 0644` — see
    `bridge/udev/60-instantlink-bridge-backlight.rules` and the commit message).
- Service: `instantlink-bridge.service`
- Install root: `/opt/InstantLinkBridge`
- Config root: `/etc/InstantLinkBridge`
- Runtime user/group: `ib:ib`
- Hotspot SSID pattern: `InstantLink-XXXX`
- Hotspot address: `192.168.8.1/24`
- USB admin address: `192.168.7.1/24`
- FTP port: `21`
- Native backend: `/opt/InstantLinkBridge/lib/libinstantlink_ffi.so`
- Sync service (plan 050): active only in Sync mode; HTTP `:8721`, Bonjour
  `_instantlink._tcp`, token at `/etc/InstantLinkBridge/sync.token`, outbox at
  `/var/lib/InstantLinkBridge/sync-outbox/`. Full API in `docs/reference/sync-api.md`.
- Virtual LCD (plan 054-A): in Sync mode, `GET /v1/screen` (live 240×240 PNG) + `POST /v1/input`
  on the same port, gated by `[sync].remote_ui` (default true).
- The device file still contains the retired `[sync] destination = "both"`; current code maps
  this legacy value to Print. Fresh installs default to `print`, and the UI writes only `print` or
  `iphone` (Sync).

## iPhone Sync (plan 050) — deployed 2026-07-14

Bridge 0.1.17 added the iPhone-sync path: received camera photos spool to a disk outbox and are
served to the iOS app over a bearer-token HTTP API (`/v1/status|queue|photos/{id}|photos/{id}/ack`)
discovered via Bonjour. Verified end-to-end on the device with no printer involved:

- FTP upload from a hotspot-subnet source was accepted with the printer absent (destination-aware
  STOR preflight), spooled (`sync.outbox_added`), and print was skipped quietly
  (`sync.print_skipped_printer_unready`).
- From the deploy host over USB admin: 401 without token; queue listed the item; the download was
  sha256-identical to the upload; `Range` returned 206; ack drained the outbox to depth 0.
- Bonjour initially advertised only `192.168.7.1` because registration raced the hotspot at boot —
  fixed in `8f24c4c` (30 s address refresh, also covers runtime Wi-Fi mode switches); the journal
  now shows `addresses=192.168.8.1,192.168.7.1`.

New runtime deps `zeroconf`/`segno`/`ifaddr` are pinned in `requirements/constraints.txt`. The Pi
had no outbound internet, so the aarch64/cp313 wheels were downloaded on the deploy host
(`pip download --platform manylinux_2_17_aarch64 --only-binary :all:`), scp'd over, and installed
into `/opt/InstantLinkBridge/.venv` before the source deploy. Fold them into the provisioning
offline-deps bundle for fresh devices.

### On-device iPhone session (2026-07-15)

Ran the real iOS app (free-team signed) against the Bridge. Two bugs found and fixed by driving the
actual hardware, both in `502a3bf`:

- **`.HIF` never saved.** Sony writes HEIF stills as `.HIF`, an extension iOS maps to no image
  type, so `PHPhotoLibrary` rejected every save and the app re-downloaded the 6.4 MB file each
  poll. `PhotoSaver` now sets the UTI explicitly (`.HIF`→HEIF, `.ARW`→Sony RAW).
- **Retry loop on complete staging.** Once a full file was staged (from the failed save), the
  resume logic requested `bytes=<size>-` forever (a 416). `downloadPhoto` now verifies the staged
  bytes against the item sha and goes straight to save when complete; corrupt/oversized partials
  restart from zero.
- **Outbox chip stale after restart.** The spool index reloads on boot but the LCD chip started at
  a stale 0 until the next add/ack — startup now announces the reloaded depth
  (`announce_initial_outbox_depth`). Verified live via `GET /v1/screen` showing `iPhone: 1 pending`.

Diagnostics that worked well: `GET /v1/screen` for a live LCD screenshot, `tcpdump` on `wlan0`
port 8721 for the request/`Range` pattern, and `devicectl … process launch --console` for the
app's own logs. Free-team friction: iOS re-prompts to trust the developer profile on every
reinstall (Settings ▸ General ▸ VPN & Device Management), and drops the internet-less hotspot when
idle — both disappear with a paid membership.

Remaining hardware validation: confirm `.HIF` now lands in Photos (the fixed build was installed
but awaited a profile re-trust at session end); run the hotspot-tolerance soak; and exercise the
physical Print/Sync switch with a live Printer and iPhone.

The old `/opt/InstantBridge` install, `/etc/InstantBridge` config, and `instantbridge.*` unit files
are legacy. They were removed from `riverps-rpi-zero-2w` on 2026-05-25 with
`scripts/cleanup-legacy-instantbridge.sh /`. Run the same script after confirming
`instantlink-bridge.service` is healthy on any migrated device.

## Deployment

Normal deploy when the Pi is reachable over USB admin Ethernet:

```bash
INSTANTLINK_BRIDGE_HOST=192.168.7.1 \
INSTANTLINK_BRIDGE_USER=hongjunwu \
INSTANTLINK_BRIDGE_OFFLINE_DEPS=1 \
scripts/deploy-to-pi.sh --system --instantlink-artifacts --deps --restart
```

Use `INSTANTLINK_BRIDGE_SEED_VENV=/opt/InstantBridge/.venv` only for one-time migration from an old
device where `/opt/InstantLinkBridge/.venv` does not yet exist and the Pi has no outbound internet.
After migration, the new install owns its own virtualenv.

The deploy script records:

- `/opt/InstantLinkBridge/.deployment/deployment-manifest.json`
- `/opt/InstantLinkBridge/.deployment/instantlink-artifacts-manifest.json`
- `/opt/InstantLinkBridge/.deployment/runtime-deps-manifest.json`
- `/opt/InstantLinkBridge/.deployment/runtime-installed-packages.txt`
- `/opt/InstantLinkBridge/.deployment/runtime-apt-packages.txt`

The Pi may have no outbound NTP route while it is serving Bridge Wi-Fi. `scripts/deploy-to-pi.sh`
therefore syncs the Pi clock from the deploy host before copying files. Leave this enabled for
normal maintenance; set `INSTANTLINK_BRIDGE_SYNC_CLOCK=0` only if the deploy host clock is wrong.

## Verification Checklist

Run these after every device deploy:

```bash
systemctl status instantlink-bridge.service --no-pager -l
/opt/InstantLinkBridge/.venv/bin/instantlink-bridge --version
sudo ss -ltnp sport = :21
sudo ss -ltnp sport = :8721  # present only in Sync mode
ip -br addr
nmcli -t -f NAME,TYPE,DEVICE,STATE con show --active
journalctl -u instantlink-bridge.service --since "5 minutes ago" --no-pager
```

Expected healthy state:

- `instantlink-bridge.service` is `active (running)`.
- `instantbridge.service` is absent or disabled/inactive.
- `wlan0` has `192.168.8.1/24` when Bridge Wi-Fi is active.
- `usb0` has `192.168.7.1/24` when connected to an admin host.
- FTP accepts the configured user on `192.168.8.1:21` in hotspot mode.
- Sync/virtual-LCD `:8721` is absent in Print mode and listens in Sync mode.
- Logs contain `ftp.server_started`, `bridge.ready`, and `instantlink.library_loaded`.
- Offline-printer status warnings are rate-limited; do not reintroduce per-second warning spam while
  keeping the UI scan loop responsive.
- Source-only deploys must preserve `/opt/InstantLinkBridge/lib` and
  `/opt/InstantLinkBridge/bin`; the native FFI library and CLI live there.
- The deployed NetworkManager state should contain one `InstantLink Bridge-Hotspot` profile and no
  legacy `InstantBridge-Hotspot` profile.

## Current Hardware Notes

- The Waveshare ST7789 display path is wired through the bridge UI and boot splash units.
- The active UPS is a SupTronics/Geekworm X306 18650 shield. It has no host-readable fuel gauge, so
  the UI must not show fake battery percentage.
- Latest on-device audit, 2026-07-22:
  - `instantlink-bridge.service` was active/enabled with `NRestarts=0`.
  - `instantlink-bridge-manager.service` was active with `NRestarts=0`.
  - `/opt/InstantLinkBridge/.venv/bin/instantlink-bridge --version` reported Python 3.13.5,
    BlueZ 5.82, Debian 13.
  - Hotspot mode was active on `wlan0` at `192.168.8.1/24`; USB admin was active on `usb0` at
    `192.168.7.1/24`; FTP was listening on `0.0.0.0:21`, and manager HTTP was listening on both
    device addresses at `:8742`.
  - Legacy config value `both` parsed as Print, and `:8721` was correctly closed in that mode.
  - `/opt/InstantLinkBridge/lib/libinstantlink_ffi.so` loaded successfully.
  - The saved Printer `INSTAX-52006924` was not advertising, so the Bridge remained in its
    printer-searching flow; the repeated scan progress was healthy and status warnings remained
    rate-limited.
  - Earlier Printer/BLE history:
    - The old BlueZ bond for `INSTAX-52006924 (IOS)` was removed after native connects failed with
      BlueZ `InProgress`, `le-connection-abort-by-local`, and `Timeout waiting for reply`.
    - A 2026-05-25 follow-up saw both `INSTAX-52006924 (ANDROID)` and
      `INSTAX-52006924 (IOS)`, then native connect reached GATT but failed with
      `write characteristic not found`. Commit `9a54b4f` retries Linux BLE characteristic
      discovery; commit `8860be6` includes that fix plus display idle defaults. Fresh ARM64
      artifacts were deployed from `8860be6`.
    - After the failed connect attempts, the Printer stopped advertising in both InstantLink and
      BlueZ scans. The LCD should show the no-Printer/pairing flow until the Printer is
      power-cycled and paired again from the Bridge.
    - Runtime idle display timers were dropped in source defaults (commit `ad638be`): dim after
      30 s, screen off after 60 s, deep idle after 300 s, poweroff after 1800 s. The earlier
      30-minute screen-off default was effectively "never" on battery; the new defaults
      materialise the GPIO-24-LOW kill into observable power saving within the first minute of
      idle.
- Physical printing is still the remaining hardware validation step after successful re-pairing.

## Local Development Checks

From `bridge/`:

```bash
python -m ruff check src tests
python -m mypy src tests
python -m pytest -q
```

From the InstantLink workspace root:

```bash
cargo fmt --all --check
cargo test --workspace --locked
cargo clippy --workspace --locked -- -D warnings
```

The current Mac does not have `rustup`, so it cannot install the
`aarch64-unknown-linux-gnu` target locally. If Rust FFI code changes, build ARM64 artifacts on a
machine or CI runner with the proper Rust target and update the artifact manifest before deploying
with `--instantlink-artifacts`.
