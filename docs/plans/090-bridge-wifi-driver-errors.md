# Bridge Wi-Fi driver errors and hotspot continuity

## Goal and scope

Investigate the remaining `brcmf_vif_set_mgmt_ie: vndr ie set error : -52` records,
remove avoidable hotspot disruption, and preserve camera FTP and automatic Printer reconnect.
Baseline source is `3230a5c`, with runtime `4145e77` installed. Use no film or image/actuator
commands on the Printer. Independent agents cover driver sources, runtime/helper lifecycle,
benchmark isolation and adversarial review. Root owns all Pi mutations.

Hardware: Pi Zero 2 W Rev 1.0, BCM43430/1 Wi-Fi firmware 7.45.96.s1 (June 14, 2023,
FWID 01-70bd2af7 es7), Debian 13.2, kernel 6.12.47+rpt-rpi-v8, NetworkManager 1.52.1,
wpa_supplicant 2.10, BlueZ 5.82. Printer: INSTAX-52006924, Link Square. GPIO/LCD and native
FFI/CLI remain the previously verified configuration. Kernel BRCM tracing is not enabled.

## Driver evidence

- The driver maps any negative firmware reply to Linux `-EBADE` (52); this message cannot
  identify the specific firmware rejection. [Raspberry Pi fwil.c](https://raw.githubusercontent.com/raspberrypi/linux/stable_20250916/drivers/net/wireless/broadcom/brcm80211/brcmfmac/fwil.c).
- Initial source inspection found AP teardown resets firmware before clearing cached
  management IEs. Later scalar entry/return probes narrowed the residual failure to
  `brcmf_cfg80211_stop_ap` clearing probe-request IEs (`pktflag=0x10`, length 0, return -52).
  Scan calls with that flag returned 0. No pointers, IE payloads or key material were traced.
  [Raspberry Pi cfg80211.c](https://raw.githubusercontent.com/raspberrypi/linux/stable_20250916/drivers/net/wireless/broadcom/brcm80211/brcmfmac/cfg80211.c).
- The accepted [upstream correction, aba23b0](https://github.com/torvalds/linux/commit/aba23b0a6a0df84b06ed0323ce127bf7257e4025),
  clears association-response IEs for AP teardown and retains probe-request cleanup for other
  modes. Beacon/probe-response cleanup is unchanged. The installed Raspberry Pi 6.12.47
  source lacks this correction. Disabling P2P reduced scan IE length from 150 to 24 bytes but
  did not remove the failure; that diagnostic configuration is not a production fix.
- NetworkManager translates disabled WPS into `wps_disabled=1`. Supplicant normally enables
  WPS for WPA2-Personal APs unless disabled. Existing WPA2-PSK authentication can remain while
  unused enrollment advertisement is disabled. [NetworkManager 1.52.1](https://raw.githubusercontent.com/NetworkManager/NetworkManager/1.52.1/src/core/supplicant/nm-supplicant-config.c),
  [wpa_supplicant 2.10 source archive](https://w1.fi/releases/wpa_supplicant-2.10.tar.gz).

## Application findings and design

Every Bridge startup applies the saved FTP mode. The old hotspot helper modifies the profile
and activates it even when the correct AP is already healthy. NetworkManager logs show
`new-activation`, AP-DISABLED/AP-ENABLED, address loss and dnsmasq restart. These correlate with
the paired kernel errors. Runtime recovery already has generation/job guards; a Python-only
skip based on an IP address would ignore configuration drift.

The helper should retain an AP only after checking exact selected UUID, desired saved and
applied settings, live address, NetworkManager owner, activation identity and applied version.
Applied settings omit secrets, so a root-private per-boot stamp must bind the desired PSK digest
to a successful helper activation. Unknown/untrusted/malformed state or failed probes must use
the existing activation/recovery path. Root helper mutations are serialized. Keep radio-off,
home transitions, missing-interface driver recovery, SSID/PIN/channel reconciliation and
cancellation operational. Disable WPS while retaining the same WPA2-PSK/RSN/CCMP settings.

The independent review identified cancellation ownership lost through a foreground pipeline.
Direct stdin redirection keeps the owned child in the main shell. The audit also found that
background commands without explicit stdin inheritance read `/dev/null`, affecting activation
stamping and newly generated PIN writes. Validate these with actual Bash/worker/lock tests;
mocked command results alone cannot establish shell process ownership.

## Baseline and controlled WPS experiment

An initial isolated 32 MiB × four-file fixture exhausted the Pi's `/tmp` tmpfs and could not
write its report. Its temporary inputs were cleaned; no production storage fault or result is
claimed. The corrected fixture uses SD-backed `/var/tmp`, storage preflight, streaming checksums
and reporting after cleanup.

A separate instance of the installed FTP receiver accepts synthetic 8 MiB JPEG transport files
on an alternate port/private root with a checksum-only queue consumer. It cannot dispatch a
production print. One unpaced and three paced uploads overlap repeated hotspot calls. This
same-Pi hotspot-address path exercises receiver/SD/service behavior, **not wireless airtime**.
Pacing is included in the continuity timing and must not be called camera throughput. Production
FTP greeting/NOOP probes run alongside NetworkManager, USB, service and BlueZ observations.

| Phase | Three helper times, median | Errors per call | Production FTP probe failures | Upload checksums |
| --- | --- | --- | --- | --- |
| Original helper, default WPS | 3.742 s | 2 / 2 / 2 | 9 | Four pass |
| Original helper, disabled WPS | 3.744 s | 2 / 0 / 0 | 9 | Four pass |

The first disabled-WPS call tears down the previously advertised WPS AP; subsequent actual
reactivations produced no vendor-IE error. This is a measured configuration improvement,
not a kernel patch or decoded firmware error. Reactivation still interrupts FTP probes, so
WPS alone does not resolve continuity. All four transfers in each corrected phase completed
with identical checksums. Unpaced single-transfer timings are retained but are not a radio
throughput comparison. Sampling commands are serial; maximum sample spans were about 0.45 s,
so no 250 ms gap-detection claim is made.

The Printer stopped advertising at 07:50:18, before the first fixture began at 07:52:49.
These early phases do not establish connected Printer retention. The user has powered it on
again for the final locked/status-only acceptance checks. Evidence is retained under
`docs/assets/bridge-audit-090/`; raw logs and credentials remain private.


## Reviewed candidate

The final helper SHA is `736cf4ba661859b16e8f9ebf49cdd289bca7e062b33e91957a6ff925572afed2`.
Independent review cleared 76 targeted tests, including eight actual Bash cancellation/lock
cases and additional PIN creation/preservation/override/permission checks. The implementation
agent passed 110 affected tests. PSK preparation now owns its commands in the main shell;
value retrieval is read-only. The review record retains both cancellation findings/resolutions.

The first unknown-stamp apply took 6.079 s, including verification; this is not boot timing.
Three verified repeat calls had median **2.187 s**, retained one activation object path,
produced **zero vendor-IE errors and zero production FTP probe failures**. All four 8 MiB
uploads completed/checksummed. All 45 samples kept the Printer connected with fresh status,
film 0, camera readiness true, screen locked and board 600 MHz, with no retired status task.
Maximum serial monitor span was 0.407 s. Paced transfers took about 7.86 s instead of 9.35 s
under AP reactivation; the deliberate pace and local address path preclude radio speed claims.
The unpaced single-transfer result (50.54 MiB/s versus baseline 50.11) does not establish a
throughput change.

## Application deployment and residual driver gate

Clean source `982d8c6` was installed, including the separately installed privileged helper.
All 67 Python file hashes match committed source; helper copies match the reviewed SHA;
native Printer artifacts are unchanged. The complete Bridge suite passed 2,339 tests, Ruff,
strict mypy and Bash syntax gates. Strict docs also passed.

The installed helper repeat took 2.144 s with zero vendor errors and production FTP probe
outages; two isolated 8 MiB receives passed checksums. The Printer was offline for that trial.
Automatic hotspot recovery after external NetworkManager connection-down took 35.020 s
with the Printer offline, then 32.349 s with all samples retaining the connected Printer,
locked screen, 600 MHz and the same Bridge PID. The healthy-state recovery grace is 30 s.
The connected trial still emitted one vendor-IE error after a preceding radio cycle.
Status-only Bluetooth disconnect/reconnect passed in 9.547 s with freshness invalidation,
one disconnect watch, no retired status tasks, camera readiness and lock retained.

Radio-off/restore recovered functional AP and FTP service, but failed the zero-vendor-error
gate. WPS removal resolves the measured paired advertisement errors; it does not correct the
wrong probe-request cleanup in the kernel. The scalar trace and P2P diagnostic identify the
narrow upstream backport required before claiming this residual driver issue is resolved.


## Pinned kernel build and review

The matching Raspberry Pi source commit is `359f37f0faefb712add32a39f98751aea67d5c1f`.
A native two-job GCC 14 build against the packaged 6.12.47+rpt-rpi-v8 headers preserves
`CONFIG_BRCMDBG=y`'s parent `-DDEBUG` flag. The unchanged rebuild exactly matches stock
`srcversion` `FBBF7D1EF3ACBA683834518`; the exact upstream patch applies without fuzz
(with a 22-line context offset) and produces `2254D80EF43499080344466`.
An independent read-only hardware review confirms all 254 imported symbol CRCs, all 11
exported CRCs/types/namespaces, vermagic, dependencies, license and AArch64 ELF identity
match stock. The independently reconstructed patched source SHA also matches.
Candidate module SHA: `a2b930a1668775132fa9446d69bc33edc7785aed48bfa6fb35873ae6a14a02c7`.

`bridge/scripts/brcmfmac-ap-ie-backport.py` provides pinned build/attest/install/rollback/verify
operations; the unmodified upstream patch, provenance and reproduction instructions live in
`bridge/patches/`. The installer preserves packaged stock, installs only a per-kernel base
module override, retains stock companions, stages privately and serializes maintenance.
It refuses incompatible source identities/ABIs, existing overrides, unsupported signature
enforcement or boot layouts. Failed installation restores stock depmod selection. Rollback
does not require build headers. This exact-kernel override is separate from application
firmware deployment; future kernels require their own review. No P2P/MBO/firmware change.

Fresh adversarial review identified and corrected candidate identity binding, archive snapshot
ownership, failed-install stock selection, rollback header dependence, backup symlink handling
and runtime signing checks. Thirty-one focused tool tests pass, including malformed/source/ABI
inputs, failed depmod rollback and protected override ownership. Actual installation, loaded
module verification, driver trace, recovery and reboot acceptance are recorded below when
complete.


## Loaded-driver acceptance

Actual Pi install → rollback → stock selection/running verification → reinstall passed without
replacing packaged stock. A deliberate Wi-Fi-only reload retained USB/g_ether, the same Bridge
PID, locked 600 MHz and camera readiness in 6.956 s. The Printer was offline; connected retention
is not claimed for that reload. Restarting the supplicant removed the temporary P2P diagnostic.
The loaded module's sysfs srcversion and selected file match the candidate. The expected
out-of-tree module taint bit was added (1536 → 5632); no kernel/firmware upgrade or initramfs
change was performed. This is a local upstream backport, not a vendor-packaged module.

Repeating scalar probes now shows AP teardown clearing association-response IEs (`0x4`,
length 0, return 0), with normal probe-request scan handling (`0x10`, including 150-byte scan
IEs) retained. Every captured management-IE return was 0 across radio-off/on and AP-down
transitions. Probe definitions and tracing instance were removed in `finally`; no payloads or
keys captured. Evidence preserves old and new traces; this establishes the changed driver
behavior, not merely absence of a log message.


## Installed connected recovery and policy checks

Clean source `a745c9136882283dc7071fabd1f721e2d6b0b186` is installed; all 67 Python source
hashes match committed files, privileged helper matches the reviewed hash, backport tool
`7a1c34ed…966cc` matches independent clearance, and native Printer artifacts remain unchanged.
The full normal commit gates passed 2,370 Bridge tests (27 existing warnings), Ruff, strict mypy
and operational-script compilation; strict docs and targeted tool formatting passed.
The unmodified upstream patch's required context whitespace has a file-specific Git attribute,
so its primary-source digest is preserved while source whitespace checking stays enabled.

With INSTAX-52006924 powered on, the installed Bridge automatically obtained fresh Link Square
status, film 0, at locked at 600 MHz without a manual Reconnect action. External AP connection-down
recovered automatically in **32.693 s**; all samples retained the connected Printer, locked at 600 MHz,
same PID and finalfresh status/watch1/no retired tasks, with **zero vendor-IE errors**.

A radio-off fixture initially expected automatic re-enabling and timed out after80.38 s.
That expectation contradicts the deliberate-administrative-off policy in plan064 and its
existing unit test. Independent review confirmed this is a fixture error, not a software
finding; the raw failed report is preserved. All 187 observations kept PrinterConnected,
fresh status, locked at 600 MHz, same PID, watch 1 / retired tasks 0/film 0 while radio remained disabled.
Explicit helper restoration succeeded with **zero vendor-IE errors**. This is not automatic
radio recovery. The accepted policy and guard remain unchanged.

The Printer shut off before the additional external Bluetooth-disconnect check, which timed
out before mutation; that availability failure is retained. Automatic reconnection when it
was powered on and connected retention above are verified; a new external-disconnect result
is not claimed. An offline UI smoke check passed same-button triple unlock, nonblank LCD and
1000 MHz boost, then relock600 through the shared production queue/physical LCD; GPIO contacts
were not actuated. Normal service was restored and its observer/drop-in/socket removed before
reboot. Final boot persistence and normal-running log evidence follow below.


## Final reboot and connected follow-up

A real reboot loaded the selected override with exact `2254D80EF43499080344466` srcversion;
stock hash and native artifacts remain unchanged. Normal services started, FTP220/200 and
hotspot/USB were available, automatic idle returned to powersave at 600 MHz. When the user powered
on INSTAX-52006924 again, normal startup obtained fresh Link Square status automatically.

A short post-boot observer validation repeated external `Device1.Disconnect`: automatic fresh
status recovery passed in **7.170 s**, with all samples locked at 600 MHz/camera ready/same PID,
immediate stale publication and final watch 1 / retired tasks 0. Uncontrolled advertising timing precludes
a transport speedup claim. The earlier Printer-unavailable attempt remains a failed
availability fixture; this follow-up resolves the connected disconnect gate. Same-button
triple unlock restored nonblank LCD/1000 MHz, relock600 and status pause/resume/watch rearm passed.
No image, print, LED/reset or other actuator Printer commands; zero film consumed.

The observer initially inherited host-private0600 scripts during transfer, causing21 failed
startup attempts before permissions were corrected to root:ib0640. This audit setup fault and
its systemd records are retained/classified separately from production application behavior.
The observer was removed again; normal Bridge/manager services are active with0 automatic
restarts. Final normal Bridge PID1542 had no warnings/errors, GPIOv2 input/no fallback,
FTP220/200, powersave at 600 MHz, 45.084°C/throttle0x0 and no working cache or audit socket/drop-in.
The Printer was offline again at final normal capture after its idle period; no current
connected-state claim is made. Its reconnect and connected recovery checks above passed.

Fresh boot journals:504 service records / 48 flags, including42 systemd records for the
21 fixture start failures, three expected BlueZ disconnect-cleanup notes and existing
configuration/registration/offline-DNS notes. Kernel 397 records / 21 warnings, **zero vendor-IE
errors**. Existing regulator/staging GPU/media/LCD and VCHI initialization findings remain;
expected local-module taint is retained. No additional application finding or new HCI fault.
Complete raw logs stay private; sanitized evidence is under `docs/assets/bridge-audit-090/`.
Owned build/benchmark/observer artifacts were removed; production per-boot Wi-Fi stamps,
installed driver override, its private provenance and stock rollback backup remain.

Boundaries: FTP fixtures used same-Pi hotspot addressing with synthetic files, not wireless
airtime or a physical camera. Shared input queue/actual LCD used, not physical button contacts.
The kernel override is specific to this kernel and must be reviewed again on kernel changes.
