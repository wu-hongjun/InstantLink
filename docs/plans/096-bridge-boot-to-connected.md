# Faster saved-Printer lookup during startup

## Scope

Improve boot-to-connected time without changing the LCD state machine, camera FTP admission,
image preparation, Printer protocol, automatic reconnect, or screen-dependent discovery cadence.
Printer benchmarks use status/discovery requests only; no film or Printer actuators.

The previous installed run reached UI at 14.138 seconds, core FTP readiness at 14.152 seconds,
and fresh Printer status at 20.041 seconds from kernel startup. Those measurements exclude
pre-kernel firmware latency and do not establish a matched radio-availability comparison.

## Changes

- Use the agent's fresh BlueZ object snapshot to resolve selected cached identities and trust
  state. Already trusted devices need no CLI inventory/trust process. Matching untrusted devices
  retain the existing trust command. An authoritative absent device has nothing to trust; the
  registered agent authorizes it when discovered. Uncertain properties, provider failure and
  ambiguous adapter scope retain the original CLI inventory/trust fallback. Cancellation does
  not launch fallback work. Startup bond reset and live-link protection remain unchanged.

No new configuration field, API payload, native ABI, native artifact or system security policy.
The existing service launch, CPU tiers, stop cleanup and LCD/FTP startup dependencies remain.

## Evidence and review

Three subagents investigated startup, implemented the bounded changes and independently reviewed
correctness. The primary agent owns hardware operations. Source validation, adversarial findings,
boot/reconnect results and limitations will be recorded after review and hardware acceptance.

A controlled warm-cache fresh-process import probe on the Pi measured 2.584/2.599 seconds with
600 MHz powersave and 1.701/1.688 seconds with 1 GHz performance, in slow/fast/fast/slow order.
This includes process/runuser startup, retains the production service and restores its original
powersave tier. It isolates import cost; it is not a complete boot speedup measurement.

The primary review found a trust-snapshot freshness race: device revision tracking covered
connection and identity changes but omitted `Trusted`, which the new lookup consumes. A newer
trust change/invalidation could therefore leave a pending older `Trusted=true` reply acceptable.
The independent reviewer confirmed the issue. Trust signals now invalidate pending snapshots;
two integration regressions require the bounded retry to return the fresh untrusted target while
preserving the shared bus. No trust values are added to the compact disconnect-watch cache.

Initial source gate passed 2,495 tests, eight expected host GPIO fallback warnings, Ruff and
strict mypy. The race correction additionally passed 137 agent/pairing tests. A controlled normal
baseline reboot of `0d79921` reached UI 14.045 s, FTP 14.036 s and core 14.059 s; the Printer was
not advertising, so that run establishes no connected-time baseline. The attempted connected
baseline timed out before any reboot because no fresh Printer status was available.

## Rejected early CPU boost

The first candidate also tried a nonfatal `ExecStartPre` call to the existing CPU performance
helper before Python imports. The normal reboot comparison showed no clear benefit: UI
14.045→14.306 s, FTP14.036→14.916 s, core14.059→14.930 s and receive-ready20.178→20.437 s.
Process-start→import completion improved only 3.350→3.110 s; startup variation and the added
pre-start process offset the isolated import result. Existing firmware `initial_turbo=30` may
also make the hook redundant, but its effect on frequency during imports was not measured.
Independent evidence review recommended rejecting this additional startup dependency. The
pre-start hook and its two tests were removed; existing application CPU policy is retained.

## Final installed checks

Clean `4049bcd` installed and rebooted with final production changes limited to trust lookup and
trust-snapshot freshness. The systemd service is byte-identical to `0d79921`; LCD, FTP, runtime
power tiers, native artifacts and startup ordering remain unchanged. Final **2,495 tests** pass,
eight expected host GPIO warnings; Ruff, format160files, strict mypy68files and strict docs pass.
Independent final net-diff review found no blocking issues.

Baseline→final kernel-monotonic boot times: LCD14.045→13.742 s, FTP14.036→13.728 s,
core14.059→13.756 s, hotspot receive-ready20.178→19.995 s. First discovery policy15.013→14.035 s;
FFI-loaded→discovery setup0.722→0.072 s. These single reboots establish reduced setup overhead,
not a full connected-time improvement: neither run had an advertising Printer. Firmware startup
latency is excluded. No input was injected.

Awake framebuffer contains156 distinct RGB565 values at1GHz/backlight high; normal screen-off
idle subsequently returned to600MHz/powersave/backlight low (cleared framebuffer expected).
Bridge475/manager639 active with zero automatic restarts, FTP220/200, other services/backup socket
active, throttle0x0 and reviewed source/unchanged FFI hashes. Complete current-boot Bridge PID
log26records has zero warning/error matches. No physical LCD quality/contact test claim.

An isolated production FTP service on the Pi received a valid JPEG byte-for-byte into its queue,
with authenticated STOR226/NOOP200. Temporary directory/credentials/port and no consumer/native
backend guarantee no print; no physical camera or normal application dispatch claim. The first
fixture's inherited login-home cwd was unreadable by `ib`; matching production WorkingDirectory
resolved it without changing FTP code. Probe resources were removed.

Automatic boot-to-Printer and installed reconnect were pending at the initial handoff.
The first readiness probe timed out before reboot. A later readiness observer ended during the
repeat reboot before fresh status or Disconnect; neither is a passing Printer test. Source and
component validation are complete, with no film or Printer actuator use. Evidence:
[plan096 measurements](../assets/bridge-audit-096/README.md).

## Live acceptance after Printer power-on

Unchanged production4049bcd, clean manifest40e0911, passed automatic reboot→fresh Printer status
**19.186 s**, LCD13.911 s and core13.924 s. No Bridge button action before connection; film10→10.
The earlier plan095 run was20.041 s. This0.855 s lower observation is not a controlled general
speedup claim; radio/bond/cache/boot variation remains. Kernel timing excludes firmware startup.

The cached untrusted device correctly retained CLI trust before the guarded startup reset;
FFI-loaded→first discovery took0.874 s, versus0.072 s for the earlier absent-target case. Do not
generalize the offline shortcut to all connections. Remaining measured costs are interpreter
launch→boot marker3.349 s, trust/reset around0.85 s and BLE connect→service discovery1.763 s.

External BlueZ Disconnect→fresh automatic status passed **11.267 s** in normal screen-off idle.
All21 samples were samePID497/600MHz/powersave/GPIO24low/FTP220+200; film10→10. First sample
starts2.273 s after dispatch, so no continuous initial Disconnect-call observation claim.
No setup failure, manual Reconnect, physical contacts or internal lock-flag introspection.

Accepted health: Bridge497/manager655 active/zero automatic restarts, connected/fresh Printer,
throttle0x0, network/Bluetooth/backup socket active, reviewed source/unit/unchanged FFI hashes.
Full current-boot Bridge PID journal91records has zero warnings/errors. Wider service logs retain
three notices: BlueZ directory mode and no-matching-connection, plus manager hotspot bind pending
which became listening1.007 s later. Independent live evidence review accepted the checks.
Initial availability gap is complete. No film or Printer image/print/actuator commands were used.
