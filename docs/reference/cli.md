# CLI Reference

## Global Options

| Flag | Description |
|------|-------------|
| `--device <NAME>` | Target a specific printer by name |
| `--json` | Output as JSON (for machine consumption) |
| `--help` | Show help |
| `--version` | Show version |

## Commands

### `instantlink scan`

Scan for nearby Instax Link printers via BLE.

```bash
instantlink scan
instantlink scan --duration 10
instantlink scan --json
```

| Option | Default | Description |
|--------|---------|-------------|
| `--duration <SECS>` | `5` | BLE scan duration in seconds |

**JSON output:** Array of printer name strings.

---

### `instantlink info`

Show printer info: battery, film count, model, charging state, print history.

```bash
instantlink info
instantlink info --device "INSTAX-12345678"
instantlink info --duration 10
```

| Option | Default | Description |
|--------|---------|-------------|
| `--duration <SECS>` | `5` | BLE scan duration in seconds |

**JSON output:**

```json
{
  "name": "INSTAX-12345678",
  "model": "Instax Mini Link",
  "battery": 85,
  "is_charging": false,
  "film_remaining": 8,
  "print_count": 42
}
```

---

### `instantlink print <IMAGE>`

Print an image file to the connected printer.

```bash
instantlink print photo.jpg
instantlink print photo.png --quality 90 --fit contain
instantlink print photo.jpg --color-mode natural
```

| Option | Default | Description |
|--------|---------|-------------|
| `--quality <1-100>` | `97` | JPEG compression quality |
| `--fit <mode>` | `crop` | Fit mode: `crop`, `contain`, or `stretch` |
| `--color-mode <mode>` | `rich` | Color mode: `rich` (vivid) or `natural` (classic film look) |

**Fit modes:**

- **crop** — Resize to fill, cropping edges as needed
- **contain** — Resize to fit within bounds, adding white bars
- **stretch** — Stretch to exact printer dimensions

The image is automatically resized to the printer's native resolution and JPEG-compressed. If the compressed image exceeds 105KB, quality is automatically reduced.

---

### `instantlink led set <COLOR>`

Set the printer's LED to a color and pattern.

```bash
instantlink led set "#FF0000"
instantlink led set "#00FF00" --pattern breathe
```

| Option | Default | Description |
|--------|---------|-------------|
| `--pattern <type>` | `solid` | Pattern: `solid`, `blink`, or `breathe` |

**Color format:** Hex string `#RRGGBB` or `RRGGBB`.

---

### `instantlink led off`

Turn off the printer's LED.

```bash
instantlink led off
```

---

### `instantlink status`

Combined connectivity check and printer info.

```bash
instantlink status
instantlink status --json
```

**JSON output (connected):**

```json
{
  "connected": true,
  "name": "INSTAX-12345678",
  "model": "Instax Mini Link",
  "battery": 85,
  "is_charging": false,
  "film_remaining": 8,
  "print_count": 42
}
```

**JSON output (disconnected):**

```json
{
  "connected": false
}
```
