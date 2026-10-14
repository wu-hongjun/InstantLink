# Earlier startup performance and saved-Printer lookup

## Scope

Improve boot-to-connected time without changing the LCD state machine, camera FTP admission,
image preparation, Printer protocol, automatic reconnect, or screen-dependent discovery cadence.
Benchmarks use status/discovery requests only; no film or Printer actuators.

The previous installed run reached UI at 14.138 seconds, core FTP readiness at 14.152 seconds,
and fresh Printer status at 20.041 seconds from kernel startup. Those measurements exclude
pre-kernel firmware latency and do not establish a matched radio-availability comparison.

## Changes

- Apply the existing privileged CPU `performance` helper before the Python entry point imports.
  The systemd pre-start command is nonfatal and cannot prompt. Existing stop cleanup restores
  `ondemand`, including failed startup; the application continues to own awake/locked/job tiers.
- Use the agent's fresh BlueZ object snapshot to resolve selected cached identities and trust
  state. Already trusted devices need no CLI inventory/trust process. Matching untrusted devices
  retain the existing trust command. An authoritative absent device has nothing to trust; the
  registered agent authorizes it when discovered. Uncertain properties, provider failure and
  ambiguous adapter scope retain the original CLI inventory/trust fallback. Cancellation does
  not launch fallback work. Startup bond reset and live-link protection remain unchanged.

No new configuration field, API payload, native ABI, native artifact or system security policy.

## Evidence and review

Three subagents investigated startup, implemented the bounded changes and independently reviewed
correctness. The primary agent owns hardware operations. Source validation, adversarial findings,
boot/reconnect results and limitations will be recorded after review and hardware acceptance.

A controlled warm-cache fresh-process import probe on the Pi measured 2.584/2.599 seconds with
600 MHz powersave and 1.701/1.688 seconds with 1 GHz performance, in slow/fast/fast/slow order.
This includes process/runuser startup, retains the production service and restores its original
powersave tier. It isolates import cost; it is not a complete boot speedup measurement.
