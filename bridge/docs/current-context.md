# InstantLink Bridge Current Context

Last verified: 2026-07-15 on `riverps-rpi-zero-2w` (bridge 0.1.17 at commit `502a3bf`; iPhone
sync feature per plan 050 + UX audit 051 + virtual LCD 054-A, exercised on-device with a real
iPhone the same day).

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

- Hardware-verified runtime baseline: bridge changes at commit `ad638be` (Main `596230d`).
  - On-device verification 2026-06-12: LCD screen-off now drives GPIO 24 LOW after the configured
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
- Sync service (plan 050): HTTP `:8721`, Bonjour `_instantlink._tcp`, token at
  `/etc/InstantLinkBridge/sync.token`, outbox at `/var/lib/InstantLinkBridge/sync-outbox/`.
  Full API in `docs/reference/sync-api.md`.
- Virtual LCD (plan 054-A): `GET /v1/screen` (live 240×240 PNG) + `POST /v1/input` on the same
  port, gated by `[sync].remote_ui` (default true). Handy for headless debugging — a screenshot
  of the current LCD is one authed `curl` away.
- `[sync] destination = "both"` is set on `riverps-rpi-zero-2w` (photos spool for iPhone AND
  print when a printer is ready; default for fresh installs remains `print`)

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
but awaited a profile re-trust at session end); run the hotspot-tolerance soak; and re-test
both-mode with a live printer.

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
sudo ss -ltnp sport = :8721
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
- Latest on-device audit, 2026-05-25:
  - `instantlink-bridge.service` was active/enabled with `NRestarts=0`.
  - `/opt/InstantLinkBridge/.venv/bin/instantlink-bridge --version` reported Python 3.13.5,
    BlueZ 5.82, Debian 13.
  - Hotspot mode was active on `wlan0` at `192.168.8.1/24`; USB admin was active on `usb0` at
    `192.168.7.1/24`; FTP was listening on `0.0.0.0:21`.
  - `/opt/InstantLinkBridge/lib/libinstantlink_ffi.so` loaded successfully.
  - The old BlueZ bond for `INSTAX-52006924 (IOS)` was removed after native connects failed with
    BlueZ `InProgress`, `le-connection-abort-by-local`, and `Timeout waiting for reply`.
  - A 2026-05-25 follow-up saw both `INSTAX-52006924 (ANDROID)` and `INSTAX-52006924 (IOS)`, then
    native connect reached GATT but failed with `write characteristic not found`. Commit `9a54b4f`
    retries Linux BLE characteristic discovery; commit `8860be6` includes that fix plus display idle
    defaults. Fresh ARM64 artifacts were deployed from `8860be6`.
  - After the failed connect attempts, the printer stopped advertising in both InstantLink and
    BlueZ scans. The LCD should show the no-printer/pairing flow until the printer is power-cycled
    and paired again from the bridge.
  - Runtime idle display timers were dropped in source defaults (commit `ad638be`):
    dim after 30 s, screen off after 60 s, deep idle after 300 s, poweroff after 1800 s. The
    earlier 30-min screen-off default was effectively "never" on battery; the new defaults
    materialise the GPIO-24-LOW kill into observable power saving within the first minute of idle.
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
