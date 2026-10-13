# Bridge idle network and recovery lookups

## Goal and evidence

Audit the remaining dark idle CPU after kernel GPIO input. Current normal runtime uses
600 MHz with Printer offline, camera hotspot control session idle and services stable.
Three 30-second baseline samples measured 1.365%, 2.265% and 1.132% of one core. A shared
executor worker accounts for the largest process share and runs both network probes and FFI;
its CPU cannot be attributed exclusively to network queries. Native Bluetooth scanning remains
a separate cost.
A 30-second syscall diagnostic, outside accepted CPU intervals, observed eight process
launches. Network health launches `ip` every five seconds locked and every second awake;
sync address maintenance also requests snapshots. Trace time is not a CPU measurement.

Current logs show no new exception, GPIO fallback, rendering error or reconnect fault.
The two earlier rejected FTP health probes are controlled plan077 events. Printer absence
is deduplicated. An authenticated hotspot control session has no upload in the capture.

## Boundaries and implementation

Read fresh Linux rtnetlink address/link dumps through a private bounded stdlib socket.
Preserve all IPv4 addresses, prefixes, non-host scopes, administrative UP and dormant AP
behavior. Retain bounded `ip` fallback for unsupported systems or protocol/socket failure.
No address cache, dependency change, new setting or App/iOS/FFI contract change.

Preserve existing UI network cadence, coalescing, stale-generation rejection, hotspot
recovery, source policies, FTP reception, CPU tiers, wake/lock and Printer reconnect. Native
Bluetooth scan/keepalive timing is outside this change. Per-interface lookup compatibility
must remain explicit; its current assigned-address behavior differs from UP-filtered batches.

## Validation

- Independent source/log audit and fresh adversarial review.
- Parser and socket tests: complete multipart dumps, sequence/sender checks, timeout,
  truncation, malformed attributes, interrupted dump, errors and guaranteed descriptor close.
- Compare against `ip` on physical interfaces read-only. Exercise only a newly created,
  test-owned dummy interface for address/scope/multiple-prefix/admin-state changes, then delete.
- Paired full-runtime CPU intervals at 600 MHz with matched offline/idle conditions; record
  process, child, per-thread and whole-system CPU. No tracing during timing intervals.
- Validate real LCD/CPU lock/unlock, FTP server readiness and automatic network recovery;
  keep tests free of film use. Run affected local gates and full Bridge suite.
- Commit/deploy clean source, validate installed runtime and restore normal service, remove
  only owned temporary resources, update current context and sanitized evidence.

## Primary references

- [Linux Netlink introduction](https://docs.kernel.org/userspace-api/netlink/intro.html)
- [rtnetlink manual](https://man7.org/linux/man-pages/man7/rtnetlink.7.html)

## Additional log/profile finding

The initial full-runtime candidate samples were higher than the older baseline despite zero
network subprocesses. A same-process forced `ip` repeat and a native repeat separate the
network change from startup/ambient BLE variation. Do not attribute all shared executor CPU
to network probes or claim total CPU savings from query latency alone.

A subsequent syscall diagnostic identified `bluetoothctl devices` and `info` launched by
silent-link recovery for an offline Printer. The existing 30-second recovery cooldown can
make these read-only checks recur even when they correctly find no connected link. Each
observed child used roughly 0.08–0.09 CPU seconds. No-op recovery is not a new runtime fault.

Replace only that discovery with a fresh bounded BlueZ ObjectManager D-Bus snapshot. Preserve
Address and Alias identity matching, platform suffix normalization, authoritative Connected
booleans and default-controller semantics. Fast path requires one verified adapter; ambiguous
or unavailable/malformed data uses the existing CLI fallback. No negative cache, no cooldown
change and no change to disconnect/remove/trust mutations, native scanning or keepalive.

Validate shared-bus cancellation isolation, malformed/timeout fallback, connected-only identity
matching, empty/offline no-op and no pseudo addresses passed to CLI. Benchmark both changes
with no tracing during CPU intervals, and identify remaining native Bluetooth CPU separately.

- [BlueZ5.82 CLI device enumeration](https://raw.githubusercontent.com/bluez/bluez/5.82/client/main.c)
- [BlueZ Device1 contract](https://github.com/bluez/bluez/blob/master/doc/org.bluez.Device.rst)

## Candidate verification

- Fresh snapshots matched `ip` in ten physical-interface comparisons. Seven isolated namespace
  cases passed multiple prefixes, scope filtering, aliases, point-to-point local/peer, retained
  addresses on down interfaces, deletion and forty concurrent reads. Physical interfaces were
  read only; owned namespace/dummy removed.
- Direct100queries: native median **3.590ms**, ip **13.822ms**. Native parentCPU **0.3584s**,
  children0; ip parent **0.3343s**, children **1.1462s**. Separate direct-query benchmark,
  not a full-runtime or energy claim.
- Read-only BlueZ parity passed five comparisons.100fresh D-Bus lookups median **22.851ms**,
  versus10CLI lookups median **616.758ms**. FDcount **8→8**. Diagnostic process owned one
  separate bus without registering/exporting an agent or mutating devices; production uses
  its existing registered agent connection.
- Independent review caught a blocking-constructor risk in the first BlueZ draft. That draft
  was not deployed; shared-agent lookup resolves it. No remaining blocking findings. Network
  non-atomicity and existing fallback timeouts are explicit boundaries.
- Local Bridge **1645** tests, focused **221**, Ruff and strict mypy **67** files passed.
  Eleven kernel-to-production-UI cases passed with both changes, real LCD/CPU and no film.
  Physical button contacts, developed-film output and live Printer reconnect are not tested
  here; Printer is offline and native print/transport code is unchanged.

## Full-runtime candidate measurements

All sets contain three30-second dark/600MHz/offline samples; syscall tracing is separate.
Original baseline process+children **2.242%** of one core. Network-only first candidate
**3.219%** is retained rather than hidden; shared worker/startup/Bluetooth CLI activity
prevents attributing that comparison to network. Same-process forced ip/native repeats
were **1.821% /1.543%** including children.

Final combined/forced legacy/combined repeat on **one PID12639**: **1.576% /1.998% /1.754%**
including children. Six native samples pooled mean **1.665%**, approximately **16.7% less**
than the three legacy samples. Native sets have **zero child CPU** and no lookup CLI calls;
first native90s captured18network/3Bluetooth reads. Legacy90s has19ip/2devices/2info, no
mutations. Variation remains from native Printer discovery; no substantial main-process-only
CPU reduction, energy or connected-workload benefit is claimed. Shared FFI/executor and Tokio
threads remain the largest process share. Evidence includes every accepted row and counters.
