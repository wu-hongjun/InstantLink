# Wi-Fi AP+STA Experiment

Date: 2026-05-22

Device: Raspberry Pi Zero 2 W, Raspberry Pi OS Lite 64-bit Trixie, NetworkManager.

## Question

Can InstantLink Bridge keep the Pi connected to an existing Same Wi-Fi network while also advertising
the bridge hotspot for camera FTP?

## Probe

Run:

```bash
sudo scripts/probe-wifi-ap-sta.sh
```

The script logs to `/tmp/instantlink-bridge-ap-sta-probe.log`, tests normal hotspot activation, tests
bringing existing Wi-Fi back up, then tests a virtual AP interface named `ib-ap0`. It restores the
starting Wi-Fi connection on exit.

The probe requires `iw` so driver interface-combination limits can be recorded.

## Result On The Live Pi

Starting state:

- Home Wi-Fi active on `wlan0`: `netplan-wlan0-La Rivière`
- Hotspot profile present but inactive: `InstantLink Bridge-Hotspot`

Driver capability from `iw list`:

```text
#{ managed } <= 1, #{ AP } <= 1, #{ P2P-client } <= 1, #{ P2P-device } <= 1,
total <= 4, #channels <= 1
```

This means the hardware/driver can expose one station interface and one AP interface at the same
time, but they must share one RF channel.

Observed behavior:

- Activating the existing `InstantLink Bridge-Hotspot` profile on `wlan0` disconnects existing Wi-Fi
  profile. `wlan0` becomes AP mode with `192.168.8.1/24`.
- Activating the saved Wi-Fi profile again disconnects the normal hotspot profile. `wlan0` returns
  to managed station mode with `192.168.5.149/22`.
- Creating a virtual AP interface succeeds:

```bash
iw dev wlan0 interface add ib-ap0 type __ap
```

- A NetworkManager AP profile bound to `ib-ap0` can run at the same time as the saved Wi-Fi
  profile on `wlan0`.
- During the successful concurrent state:

```text
InstantLink Bridge-Hotspot-ap0  wifi  ib-ap0  active
netplan-wlan0-La Rivière   wifi  wlan0   active
wlan0                      managed, channel 11
ib-ap0                     AP, channel 1
```

The `iw list` capability says AP+managed is limited to one channel, so the channel mismatch above
needs more validation. It may work briefly, channel-switch, or become unstable under client traffic.

## Implication

The product should keep the current simple `Bridge Wi-Fi` and `Same Wi-Fi` modes because they are
deterministic.

An advanced `Hotspot + backhaul` mode is plausible on the Pi Zero 2 W, but should be implemented as
a separate, explicitly experimental path:

- Create and remove `ib-ap0` intentionally.
- Bind the bridge AP NetworkManager profile to `ib-ap0`, not `wlan0`.
- Keep the saved Wi-Fi profile on `wlan0`.
- Force or validate same-channel operation before claiming it is reliable.
- Show this as an advanced/experimental mode in the UI until camera FTP uploads are validated while
  Tailscale/existing Wi-Fi traffic remains active.
