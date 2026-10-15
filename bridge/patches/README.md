# Pi Wi-Fi AP management-IE backport

`brcmfmac-ap-management-ie-aba23b0a.patch` is the unmodified
[upstream Linux change](https://github.com/torvalds/linux/commit/aba23b0a6a0df84b06ed0323ce127bf7257e4025).
When stopping an AP, it clears the association-response vendor IE rather than the station
probe-request vendor IE. It retains station clearing and all existing AP beacon/probe-response
clearing. P2P, MBO, Bluetooth, and firmware capabilities remain enabled.

This is an explicit backport for **6.12.47+rpt-rpi-v8** on the audited Pi Zero 2 W.
It is not automatically rebuilt or installed by a Bridge firmware update. A new kernel needs
its own source/ABI review. The version-specific `updates/instantlink/brcmfmac.ko` override is
ignored when another kernel boots; the packaged module is never overwritten.

## Reproduce

Dependencies: native aarch64 Pi, GCC 14, `make`, `patch`, Python 3.11+, kmod, exact installed
kernel headers including `.config` and `Module.symvers`, and `lsinitramfs` (`initramfs-tools-core`).
No module signing is supported when `CONFIG_MODULE_SIG_FORCE=y`.

Download the exact source archive on a machine with internet access, verify its SHA-256 against
`brcmfmac-ap-management-ie-provenance.json`, then transfer it to SD-backed `/var/tmp` on the Pi.
The build tool independently verifies the archive and patch before use. Do not publish a partial
download: download to a temporary filename, verify it, then rename it to the final archive name.

Run from an InstantLink checkout or installation containing both `scripts/` and `patches/`:

```bash
python3 bridge/scripts/brcmfmac-ap-ie-backport.py build \
  /var/tmp/linux-359f37f0.tar.gz /var/tmp/instantlink-brcmfmac-build
```

Use a **new, absent build directory**. The build uses two jobs, preserves the parent's
`CONFIG_BRCMDBG=y` `-DDEBUG` flag, first rebuilds unchanged source and compares its complete
module metadata/srcversion with packaged stock, then applies the exact patch without fuzz.
The artifact gate checks complete vermagic, dependencies, license, AArch64 ELF identity,
imported CRCs against stock and headers, and all exported CRCs/types/namespaces against stock
header records. Stock vendor companions, including `brcmfmac_wcc`, remain installed.

For an already compiled unchanged baseline and patched candidate:

```bash
python3 bridge/scripts/brcmfmac-ap-ie-backport.py attest \
  /var/tmp/linux-359f37f0.tar.gz /var/tmp/source/linux-359f37f0faefb712add32a39f98751aea67d5c1f \
  /var/tmp/baseline/brcmfmac.ko /var/tmp/source/linux-359f37f0faefb712add32a39f98751aea67d5c1f/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
  /var/tmp/instantlink-brcmfmac-artifacts
```

Attestation checks every selected original source file, allowing only the exact patched
`cfg80211.c`, and pins the verified patched module srcversion. Preserve the generated manifest
and build log as deployment evidence.

## Install and activate

```bash
sudo python3 bridge/scripts/brcmfmac-ap-ie-backport.py install \
  /var/tmp/instantlink-brcmfmac-build/artifacts
```

Installation stages artifacts privately, repeats ABI/hash checks, preserves a private stock
backup and manifest under `/var/lib/InstantLinkBridgeKernelBackports/6.12.47+rpt-rpi-v8`, installs
only the base module into the per-kernel `updates/instantlink/` directory, and verifies `depmod`
selects that override. Existing overrides are refused. The installer verifies the default boot
configuration/includes and refuses initramfs images containing `brcmfmac.ko`; it does not modify
initramfs images. The audited device contains no Wi-Fi module in its initramfs.

Installation leaves the running driver unchanged. Keep USB management access and finish active
camera uploads before a deliberate Wi-Fi reload. During the validation window, stop the Bridge
service, unload a present `brcmfmac_wcc` holder first, then unload/reload only the Wi-Fi base:

```bash
sudo systemctl stop instantlink-bridge.service
if test -d /sys/module/brcmfmac/holders/brcmfmac_wcc; then
  sudo /sbin/modprobe -r brcmfmac_wcc
fi
sudo /sbin/modprobe -r brcmfmac
sudo /sbin/modprobe brcmfmac
sudo systemctl start instantlink-bridge.service
sudo python3 bridge/scripts/brcmfmac-ap-ie-backport.py verify
```

If another module still holds the Wi-Fi base, stop and inspect it; do not unload arbitrary
modules. Bluetooth is not part of the reload. Restore the configured Wi-Fi mode through normal
Bridge startup, then validate hotspot/home operation, FTP transfers, locked Printer reconnect,
kernel logs, and reboot persistence without printing film.

## Roll back

```bash
sudo python3 bridge/scripts/brcmfmac-ap-ie-backport.py rollback
```

Rollback removes only the recorded, hash-matching override and verifies that `depmod` selects
the preserved packaged stock module. It requires the matching running kernel, but does not
require build headers or GCC. Repeat the deliberate Wi-Fi reload above to restore the running
stock driver, then use `verify` to check selected and running srcversion. It never overwrites the
packaged stock module or discards another operator's override.
