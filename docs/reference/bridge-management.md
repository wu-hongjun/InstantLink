# Bridge management configuration

The Bridge manager exposes authenticated configuration at `/v1/config`. The App loads this
configuration, validates a draft and applies a field diff. The independent Printer correction
section is additive; older configurations and older responses without it default to zero.

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

When enabled, either manual lock or automatic screen-off requires any three presses to unlock.
The first input wakes the prompt and starts the awake CPU tier; the second advances its count;
the third restores the latest live screen. All three inputs are consumed, so the next input
performs a normal action. An incomplete sequence expires 10 seconds after its first press and
returns to dark idle, with its count reset. Active preparation/printing remains boosted;
background receive, Sync and Printer reconnect remain operational.

When disabled, one input wakes and repaints the screen without executing its normal action.
The physical and virtual LCDs share this behavior and the existing abstract input API. This
input guard prevents accidental button actions; it is not an authentication mechanism.
