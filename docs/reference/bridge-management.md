# Bridge management configuration

The Bridge manager exposes authenticated configuration at `/v1/config`. The App loads this
configuration, validates a draft and applies a field diff. The independent Printer correction
section is additive; older configurations and older responses without it default to zero.

## Listener recovery

The manager binds configured device addresses individually. If USB is available before the
hotspot address, it serves USB immediately and retries only the missing address, with backoff
from 1 to 10 seconds. Once all listeners bind, retries stop. A missing address does not widen
the bind to a wildcard or change USB-local authentication. If no configured address can bind,
the service fails for its existing systemd restart policy. API payloads are unchanged.

## Print review delay

`workflow.auto_print_delay_s` defaults to **1 second** when absent. Management updates accept
`1` (Review 1s), `5` (Review 5s), `0` (Print immediately) or `"off"` (Confirm each). Boolean,
negative, non-finite and other numeric values are rejected by the management API. Stored
legacy positive delays outside these choices map to the 1-second review; explicit 5-second,
immediate and manual settings are preserved. The App and Bridge settings expose all four choices.

The countdown begins after preparation displays the photo. Editing or choosing a tool switches
that photo to manual confirmation. Changing the review delay does not alter active print speed.

## Printer correction

A configuration response includes:

```json
{"correction": {"saturation": 0}}
```

A configuration update/validation diff may include:

```json
{"correction": {"saturation": 50}}
```

`correction.saturation` must be an integer between −100 and +100. Boolean, floating-point,
string and out-of-range values are rejected with a field error for `correction.saturation`.
It persists under `[correction]` in `/etc/InstantLinkBridge/config.toml`:

```toml
[correction]
saturation = 50
```

Correction compensates Printer output independently of the creative `[adjustments]` Look. It
runs at print resolution after the Look, before JPEG encoding. Zero preserves existing output.
It applies to Bridge print output and its final LCD preview; Sync originals are unchanged.
The App exposes this section separately and preserves correction when Looks change.


## Unlock input guard

Configuration responses include the UI setting:

```json
{"ui": {"unlock_requires_three_presses": true}}
```

The field defaults to `true` when absent in stored configuration or older responses. The App
preserves that default when loading an older Bridge response. A configuration update/validation
diff can toggle it:

```json
{"ui": {"unlock_requires_three_presses": false}}
```

Only JSON booleans are accepted. Strings, numbers and other types produce a field error for
`ui.unlock_requires_three_presses`. The value persists in `/etc/InstantLinkBridge/config.toml`:

```toml
[ui]
unlock_requires_three_presses = true
```

The LCD exposes the same setting at **Settings → System → Unlock: 3 presses**.

When enabled, either manual lock or automatic screen-off requires three consecutive presses of
the **same physical button** to unlock. The first input wakes the prompt and starts the awake CPU
tier; the second advances its count; the third restores the latest live screen. A different
button resets progress to one for that button. Every accepted press restarts the 10-second
inactivity timer, whether it advances or resets the count.
KEY1 and joystick press remain distinct, despite both normally generating Select. Physical
buttons must be released between presses.

For virtual input, repeat the same action three consecutive times. A different action resets
progress to one; remote and physical inputs have separate identities and cannot combine their
presses. All inputs are consumed until unlocking completes, so the next input performs a normal
action. An incomplete sequence expires 10 seconds after its last accepted press and returns to
dark locked idle, with its count reset. FTP, status activity and screen polling do not restart the
unlock timer. Active preparation/printing remains boosted; background receive,
Sync and Printer reconnect remain operational.

When disabled, one input wakes and repaints the screen without executing its normal action.
The Linux framebuffer packs pixels as little-endian RGB565 using native Pillow band operations,
with the same channel quantization and pixel ordering. Changed frames are drawn and written
synchronously; wake restores pixels before enabling the backlight.

The physical and virtual LCDs share this behavior and the existing abstract input API. This
input guard prevents accidental button actions; it is not an authentication mechanism.

### Runtime maintenance and diagnostics

When the screen is dark, display maintenance waits up to five seconds rather than polling
every 0.35 seconds. Printer-readiness and iPhone-activity expiry deadlines shorten that wait;
display transitions interrupt it immediately. About-page version/metrics collectors are not
started while the screen is dark. Camera receive, network recovery, Printer polling and the
configured CPU tiers continue independently.

Physical buttons use a Linux GPIO v2 event descriptor on supported Raspberry Pi controllers.
The kernel applies the existing 50 ms stable debounce; asyncio reads only when an edge is
ready. This removes the input alert thread's frequent idle wakeups. All eight mappings,
physical button identities, held-press behavior and lock/unlock rules are preserved. If
requests or event reads fail, input falls back to GPIO Zero/lgpio. Lost event sequences
resynchronize current levels and discard uncertain presses, preventing a partial sequence
from accidentally unlocking. Startup logs identify the backend and any fallback.

At the default INFO log level, successful Printer status is recorded on first observation,
value/recovery changes and a five-minute heartbeat. Unchanged intermediate observations and
routine scan progress are DEBUG. Expected Printer absence is recorded once at INFO until
its state changes; genuine communication failures retain rate-limited warnings. Use the
Bridge executable's `--log-level DEBUG` option when detailed poll/scan records are needed.

Cancelling a native operation retains serialization until its blocking worker has finished
or the existing stuck-worker deadline triggers recovery. Completed worker/sender failures
are distinguished from watchdog deadline expiry, and obsolete status results cannot initiate
recovery or alter the current UI. Retired status tasks remain owned through shutdown cleanup.

Printer polling checks the saved bond before its first fetch after startup. The existing
BlueZ guard removes only disconnected identities and preserves the saved selection; a live
Printer keeps its bond. Polling waits for active rebond and silent-link recovery before connecting again.

After a previously responsive Printer stops responding, the Bridge permits two prompt
status/reconnect retries with at least 250 ms between attempts. If they fail, it resumes
the configured offline search period; startup with an absent Printer keeps that ordinary
cadence. The existing “Restart printer” retry interval still applies. Confirmed native
session closure retires a cached link immediately; uncertain status failures retain the
existing two-failure tolerance.

Linux address probes read fresh bounded kernel snapshots, avoiding repeated `ip` launches.
Scope, prefix, administrative state and polling/recovery timing are preserved. Incomplete,
interrupted or unavailable snapshots use the existing bounded `ip` fallback; there is no
address cache.

Silent Printer recovery reads current connected identities through the existing BlueZ
agent connection. Exact addresses and normalized Alias matching are preserved; ambiguous
adapter topology or unavailable/invalid data uses the existing CLI lookup. Empty/offline
snapshots require no discovery commands. Disconnect rules, scan cadence and recovery cooldown
are unchanged; cancellation does not disconnect the shared agent.

Before a proactive bond reset, the Bridge checks all matching connected identities using a
fresh, bounded snapshot on that same agent bus. Exactly one known adapter is required; unknown
connection state, incomplete scope, ambiguous topology or unavailable data uses the established
CLI gate. A live identity prevents bond removal. Removal commands and their ordering are unchanged.

With native libraries providing `instantlink_connect_named_with_status`, a fresh status request
uses the successful connection's initial Printer read directly. It is a handoff within that
request, with no retained status cache or TTL. Every later poll queries the Printer again.
Older libraries use the established connect-and-status path; an error from the new function
does not trigger another connect API. Print setup retains its existing connection path.

After a disconnect event, the serialized loop finishes guarded bond cleanup before its first
fresh scan. Recovery owners are joined before reconnect or print handoff; CLI subprocesses are
killed and reaped on cancellation. Printing aborts if mutating cleanup cannot finish within
six seconds, while unfinished owners remain retained for recovery. Periodic fallback and the
existing bounded reconnect burst are preserved.

Native notification setup overlaps the read-only MTU lookup with its existing 200 ms settling
interval. Missing metadata or the default ATT MTU is refreshed after settling within the
original total budget; known small limits are retained on refresh failure. No initial command
can start before settling, and fragment fallback, print bytes and command pacing are preserved.

Native Linux discovery uses fresh bulk BlueZ metadata to skip clearly unrelated
cached devices. Possible Printers retain their existing property and connection
checks. Invalid or unavailable metadata falls back to those checks; scan cadence,
unfiltered advertisements and saved-Printer reconnect behavior are preserved.
The extra reader has a bounded query budget and owns its separate bus resource.

The selected Printer also has a disconnect watch on the existing agent bus. After
successful status, a complete signal-maintained Device1 identity snapshot can identify a unique
live physical path without another bus request. It is seeded by existing authenticated reads,
bound to the current agent lifecycle/BlueZ owner and used only while the shared bus is connected.
Missing, invalidated or ambiguous state retains the bounded fresh-snapshot fallback. The identity
cache is capped at 512 device rows, adds no startup task or query, and is never used for the fresh
bond-removal gate. Stale iOS/Android identities are ignored and ambiguous identities retain polling.
Authenticated connection-loss, device/adapter-removal and BlueZ-owner events wake the serialized status
loop, including its ordinary waiting gap. Callbacks do not issue Printer commands or change
CPU tiers. Printing pauses and selection/generation changes disarm the watch. A delayed registration must
still own its token and selected address/name before its result can retain a subscription.

Signals arriving during status or watch setup remain pending, so an earlier reply cannot
restore readiness after the link has dropped. A 250 ms recovery gap bounds repeat cycles;
bond cleanup and existing two-retry/offline cadence remain. Ten-second periodic status
checks remain the fallback. An arming failure is tried/logged once per connected episode,
then a new status generation or offline/reconnect transition permits another attempt.
There are no per-poll watch snapshots or new idle queries.

The pairing agent tracks BlueZ owner changes on its existing bus and registers
again after a daemon restart. If the agent manager or selected adapter appears
late, its interface-added event retries registration. These watches do not poll
while ready. Owner changes invalidate stale registration and snapshot results;
shutdown removes its matches and waits for owned tasks to finish.

Network readiness uses addresses from administratively enabled interfaces. An interface that
is down can retain its IPv4 address; that address no longer suppresses hotspot recovery or
appears in Bonjour advertisement candidates. Carrier is not required for dormant interfaces.
