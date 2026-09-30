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
