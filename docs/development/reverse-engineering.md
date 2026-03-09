# Reverse Engineering the Instax Link BLE Protocol

This guide documents how the Instax Link protocol was reverse-engineered by the open-source community, and provides a methodology for adding support for future devices.

## Background

The Instax Link printers (Mini Link, Mini Link 2, Square Link, Wide Link) use a proprietary BLE GATT protocol that replaces the WiFi-based protocol of older SP-1/SP-2/SP-3 models. The protocol was reverse-engineered collaboratively via [jpwsutton/instax_api#21](https://github.com/jpwsutton/instax_api/issues/21), with working implementations in [javl/InstaxBLE](https://github.com/javl/InstaxBLE) (Python) and this project (Rust).

## Methodology

### Step 1: Capture BLE Traffic

**Android (preferred for packet capture):**

1. Enable *Bluetooth HCI snoop log* in Developer Options
2. Open the official Instax app and perform the action you want to capture (print, LED control, etc.)
3. Disable the snoop log
4. Pull the log file:
   ```bash
   adb pull /data/misc/bluetooth/logs/btsnoop_hci.log
   ```

**macOS (PacketLogger):**

Apple's PacketLogger (from [Additional Tools for Xcode](https://developer.apple.com/download/all/)) can capture BLE traffic directly.

### Step 2: Analyze in Wireshark

1. Open the `.log` file in Wireshark
2. Filter with `btspp` (for RFCOMM/SPP traffic) or `btatt` (for BLE GATT)
3. Look for writes to the Write Characteristic (`70954783-...`) and notifications from the Notify Characteristic (`70954784-...`)

### Step 3: Identify Packet Structure

All Instax Link packets follow this format:

```
[Header:2B] [Length:2B] [Opcode:2B] [Payload:variable] [Checksum:1B]
```

- **Client→Printer header**: `0x41 0x62` (ASCII "Ab")
- **Printer→Client header**: `0x61 0x42` (ASCII "aB")
- **Length**: Big-endian u16, total packet size
- **Checksum**: `(255 - (sum_of_all_preceding_bytes & 255)) & 255`
- Validation: `sum(entire_packet_including_checksum) & 255 == 255`

### Step 4: Decode Opcodes

The opcode's first byte is the **command group**, second byte is the **command within group**:

| Group | Purpose | Examples |
|-------|---------|----------|
| `0x00` | Device info & capabilities | Version info, device queries |
| `0x01` | Power & connection control | Shutdown, reset, sleep, BLE connect |
| `0x02` | Support function queries | Battery, film, print history |
| `0x10` | Image transfer | Download start/data/end, print |
| `0x20` | Firmware update | FW download, upgrade, backup |
| `0x30` | Hardware settings | Accelerometer, LEDs, printer head |
| `0x80` | Camera settings | Live view, post-view upload |

### Step 5: Decode Response Format

Responses include a **return code** byte after the opcode:
- `0x00` = success
- Non-zero = error/rejection

For multiplexed queries (opcode `0x0002`), the response also includes the InfoType byte so you can match responses to requests.

### Step 6: Android App Decompilation

The official Instax app can be decompiled with jadx or apktool to discover:
- Event type enumerations (all 64+ command/event types)
- Payload field definitions
- Image encoding parameters
- Protocol state machines

Key findings from app decompilation:

```
SUPPORT_FUNCTION_AND_VERSION_INFO(0, 0)
DEVICE_INFO_SERVICE(0, 1)
SUPPORT_FUNCTION_INFO(0, 2)
IDENTIFY_INFORMATION(0, 16)
SHUT_DOWN(1, 0)
RESET(1, 1)
AUTO_SLEEP_SETTINGS(1, 2)
BLE_CONNECT(1, 3)
PRINT_IMAGE_DOWNLOAD_START(16, 0)
PRINT_IMAGE_DOWNLOAD_DATA(16, 1)
PRINT_IMAGE_DOWNLOAD_END(16, 2)
PRINT_IMAGE_DOWNLOAD_CANCEL(16, 3)
PRINT_IMAGE(16, 128)           // 0x1080
REJECT_FILM_COVER(16, 129)     // 0x1081
FW_DOWNLOAD_START(32, 0)       // 0x2000
FW_DOWNLOAD_DATA(32, 1)
FW_DOWNLOAD_END(32, 2)
FW_UPGRADE_EXIT(32, 3)
FW_PROGRAM_INFO(32, 16)
FW_DATA_BACKUP(32, 17)
FW_UPDATE_REQUEST(32, 18)
XYZ_AXIS_INFO(48, 0)           // 0x3000
LED_PATTERN_SETTINGS(48, 1)    // 0x3001
AXIS_ACTION_SETTINGS(48, 2)
POWER_ONOFF_LED_SETTING(48, 3)
AR_LED_VIBRATION_SETTING(48, 4)
ADDITIONAL_PRINTER_INFO(48, 16) // 0x3010
PRINTER_HEAD_LIGHT_CORRECT_INFO(48, 17)
PRINTER_HEAD_LIGHT_CORRECT_SETTINGS(48, 18)
```

## Transport Variants

The same packet protocol works over three transport layers:

| Transport | Platform | Notes |
|-----------|----------|-------|
| **BLE GATT** | iOS, macOS, Linux | Primary. Uses custom service UUID `70954782-...`. MTU=182, packets fragmented into sub-packets. |
| **RFCOMM/SPP** | Android | Classic Bluetooth serial. Same packet format, no MTU fragmentation needed (MTU ~990). |
| **USB CDC ACM** | Any (via USB cable) | Printer appears as `/dev/ttyACM0`. Vendor `04cb`, Product `5019`. Same packet format. |

### BLE Device Discovery

The printer advertises two BLE names:
- `INSTAX-{serial}(IOS)` — connect to this one (BLE GATT)
- `INSTAX-{serial}(ANDROID)` — RFCOMM/SPP endpoint

Manufacturer data key: `0x04d8`, value: `01 00`.

## Device Info Queries (Opcode 0x0001)

The `DEVICE_INFO_SERVICE` command uses a sub-index byte in the payload to select which field to query:

| Sub-index | Field | Example Response |
|-----------|-------|------------------|
| `0x00` | Manufacturer | `FUJIFILM` (ASCII, length-prefixed) |
| `0x01` | Model | `SP-4` (internal model name for Mini Link) |
| `0x02` | Serial Number | `10458647` (ASCII) |
| `0x03` | Unknown version | `0000` |
| `0x04` | Hardware version | `0102` |
| `0x05` | Firmware version | `1.00` |

Response format: `[return_code:1B] [sub_index:1B] [string_length:1B] [ASCII data...]`

Internal model names:
- Mini Link = `SP-4`
- Mini Link 2 = likely `SP-5` (unconfirmed)
- Square Link = unknown
- Wide Link = unknown

## LED Animation Protocol

The LED system supports multi-frame animations (not just static colors):

```
Payload: [when:1B] [frame_count:1B] [speed:1B] [repeat:1B] [B,G,R:3B per frame...]
```

| Field | Values |
|-------|--------|
| `when` | `0`=immediate, `1`=on print start, `2`=on print complete, `3`=pattern switch |
| `frame_count` | Number of color frames in animation |
| `speed` | Frame duration (higher = slower) |
| `repeat` | `0`=play once, `1-254`=repeat N times, `255`=loop forever |
| Colors | **BGR** format (blue, green, red — not RGB) per frame |

**Hardware-verified** (Instax Square Link, March 2026):
- **BGR byte ordering confirmed** — sending `[B=0, G=0, R=255]` produces red light, `[B=255, G=0, R=0]` produces blue light.
- **`repeat=0xFF` required** for static colors — `repeat=0` causes the color to flash once and revert to white.
- **`speed=1`** works for static colors (speed=0 caused the color to not display correctly).
- For a simple static red: `[when=0, count=1, speed=1, repeat=255, B=0, G=0, R=255]`

## Accelerometer Data (Opcode 0x3000)

Returns orientation data as a packed struct:

```
Format: <hhhB (little-endian)
  x: i16 — X axis acceleration
  y: i16 — Y axis acceleration
  z: i16 — Z axis acceleration
  orientation: u8 — derived orientation value
```

The official Nintendo app continuously logs accelerometer values (discovered via `adb logcat "InstaxApplication:D *:S"`), suggesting this was used for motion-based features.

## Image Encoding

Key observations from the community:
- Images are **always JPEG** (not raw pixels)
- Variable block counts per image (depends on JPEG file size, not pixel count)
- This explains why 69 blocks x 900 bytes = 62,100 bytes, not 600x800x3 = 1,440,000 bytes
- Maximum JPEG size: ~105 KB
- Last chunk is **zero-padded** to full chunk size
- Quality should be optimized via binary search to stay under the size limit

## Known Unknowns / Future Work

### Confirmed on hardware (Instax Square Link):
- BGR LED byte ordering (not RGB)
- LED repeat=255 required for persistent static colors
- LED speed=1 works for static; speed=0 does not display correctly
- Print flow: DOWNLOAD_START → DATA chunks (ACK per chunk) → DOWNLOAD_END → PRINT_IMAGE
- Accelerometer opcode exists but not yet tested on hardware

### Not yet reverse-engineered:
1. **Firmware update flow** — Opcodes 0x2000-0x2012 exist but payload formats are unknown
2. **Camera settings** (0x80xx) — For models with camera features
3. **REJECT_FILM_COVER** (0x1081) — Purpose unclear, possibly for cartridge door detection
4. **AXIS_ACTION_SETTINGS** (0x3002) — May configure motion-triggered actions
5. **POWER_ONOFF_LED_SETTING** (0x3003) — Startup/shutdown LED behavior
6. **AR_LED_VIBRATION_SETTING** (0x3004) — AR-related haptic/LED feedback
7. **PRINTER_HEAD_LIGHT_CORRECT** (0x3011/0x3012) — Print head calibration
8. **IDENTIFY_INFORMATION** (0x0010) — Unknown identification data
9. **BLE_CONNECT** (0x0103) — BLE-specific connection reservation command

### Adding support for new models:
1. Capture BLE traffic with the official app
2. Query Image Support Info — response dimensions identify the model
3. Test with known chunk sizes (900B for mini/wide, 1808B for square)
4. If a new model uses different chunk sizes, the DOWNLOAD_START response may contain the requested block size
5. Verify JPEG quality limits — 105 KB may differ for newer models

## Community References

- [jpwsutton/instax_api](https://github.com/jpwsutton/instax_api) — Original WiFi protocol RE (SP-1/2/3)
- [jpwsutton/instax_api#21](https://github.com/jpwsutton/instax_api/issues/21) — BLE protocol RE thread (this document's primary source)
- [javl/InstaxBLE](https://github.com/javl/InstaxBLE) — Python BLE implementation (Mini, Square, Wide)
- [linssenste/instax-link-web](https://github.com/linssenste/instax-link-web) — Web Bluetooth implementation
- [dgwilson/ESP32-Instax-Bridge](https://github.com/dgwilson/ESP32-Instax-Bridge) — ESP32 bridge
