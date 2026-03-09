# BLE Protocol Reference

This documents the Instax Link BLE protocol as reverse-engineered by the open-source community.

## BLE Service

| Item | UUID |
|------|------|
| Service | `70954782-2d83-473d-9e5f-81e1d02d5273` |
| Write Characteristic | `70954783-2d83-473d-9e5f-81e1d02d5273` |
| Notify Characteristic | `70954784-2d83-473d-9e5f-81e1d02d5273` |

## Packet Format

All communication uses the same packet structure:

```
[0x41 0x62] [length:2B] [opcode:2B] [payload...] [checksum:1B]
```

| Field | Size | Description |
|-------|------|-------------|
| Header | 2 bytes | Request: `0x41 0x62`, Response: `0x61 0x42` |
| Length | 2 bytes | Big-endian, total packet size (header + length + opcode + payload + checksum) |
| Opcode | 2 bytes | Command identifier (big-endian) |
| Payload | variable | Command-specific data |
| Checksum | 1 byte | `(255 - (sum_of_preceding_bytes & 255)) & 255` |

Minimum packet size is 7 bytes (header + length + opcode + checksum, no payload).

## Checksum

The checksum is computed over all bytes preceding it (header + length + opcode + payload):

```rust
fn checksum(data: &[u8]) -> u8 {
    let sum: u32 = data.iter().map(|&b| b as u32).sum();
    ((255 - (sum & 255)) & 255) as u8
}
```

## MTU Fragmentation

BLE packets larger than 182 bytes are split into sub-packets for transmission. The receiver reassembles them using the length field in the first sub-packet. The `PacketAssembler` buffers incoming fragments until a complete packet is received.

## Opcodes

### Query Commands

All status queries use a single opcode (`0x0002` SUPPORT_FUNCTION_INFO) with an InfoType byte in the payload to select which information to retrieve.

| Opcode | Name | Payload | Description |
|--------|------|---------|-------------|
| `0x0001` | Device Info Service | SubIndex(1B) | Query device info field by sub-index |
| `0x0002` | Support Function Info | InfoType(1B) | Multiplexed query — InfoType selects the data |

**Device Info sub-indices** (payload byte for opcode `0x0001`):

| Sub-index | Field | Example Response |
|-----------|-------|------------------|
| `0x00` | Manufacturer | `FUJIFILM` |
| `0x01` | Model | `SP-4` (Mini Link internal name) |
| `0x02` | Serial Number | `10458647` |
| `0x03` | Unknown version | `0000` |
| `0x04` | Hardware version | `0102` |
| `0x05` | Firmware version | `1.00` |

Response format: `[return_code(1B)] [sub_index(1B)] [string_length(1B)] [ASCII data...]`

**InfoType values** (payload byte for opcode `0x0002`):

| InfoType | Name | Response Data |
|----------|------|---------------|
| `0x00` | Image Support Info | Width(2B), Height(2B) — used for model detection |
| `0x01` | Battery Status | State(1B), Level(1B, 0–100) |
| `0x02` | Printer Function Info | Byte: bits 0–3 = film remaining, bit 7 = charging |
| `0x03` | Print History | Print count(2B, big-endian) |

**Response format** for `0x0002`: `[return_code(1B)] [info_type(1B)] [data...]`

### Image Transfer

| Opcode | Name | Payload | Response |
|--------|------|---------|----------|
| `0x1000` | Download Start | PictureType(1B) + PrintOption(1B) + PrintOption2(1B) + Zero(1B) + ImageSize(4B, big-endian) | ACK status(1B) |
| `0x1001` | Data | ChunkIndex(4B, big-endian) + chunk data | ACK status(1B) |
| `0x1002` | Download End | (none) | ACK status(1B) |
| `0x1003` | Download Cancel | (none) | ACK status(1B) |
| `0x1080` | Print Image | (none) | Print status(1B) |

ACK status `0` indicates success; any other value means the operation was rejected.

### Power & Connection Control

| Opcode | Name | Payload | Description |
|--------|------|---------|-------------|
| `0x0100` | Shut Down | (none) | Power off the printer |
| `0x0101` | Reset | (none) | Reset the printer |
| `0x0102` | Auto Sleep Settings | TBD | Configure auto-sleep timer |
| `0x0103` | BLE Connect | TBD | BLE-specific connection reservation |

### LED & Sensors

| Opcode | Name | Payload | Description |
|--------|------|---------|-------------|
| `0x3000` | XYZ Axis Info | (none) | Query accelerometer |
| `0x3001` | LED Pattern Settings | See below | Set LED color/animation |
| `0x3010` | Additional Printer Info | Mode-specific | Query additional info |

**LED Pattern payload format:**

```
[when:1B] [frame_count:1B] [speed:1B] [repeat:1B] [B,G,R per frame:3B each...]
```

| Field | Values |
|-------|--------|
| `when` | `0`=immediate, `1`=on print start, `2`=on print complete, `3`=pattern switch |
| `frame_count` | Number of color frames (1 for static, >1 for animation) |
| `speed` | Frame duration (higher = slower) |
| `repeat` | `0`=once, `1-254`=repeat N times, `255`=loop forever |
| Colors | **BGR** byte order per frame |

For a simple static color: `[0x00, 0x01, 0x01, 0xFF, B, G, R]` (speed=1, repeat=forever)

**Note**: `repeat=0` (play once) causes the color to flash and revert to white. Use `repeat=0xFF` to keep the color on. Confirmed on Instax Square Link hardware.

**Accelerometer response format:** `<hhhB` — three signed i16 (x, y, z) + one u8 (orientation)

### Firmware Update (not implemented)

| Opcode | Name | Description |
|--------|------|-------------|
| `0x2000` | FW Download Start | Begin firmware transfer |
| `0x2001` | FW Download Data | Firmware data chunk |
| `0x2002` | FW Download End | End firmware transfer |
| `0x2003` | FW Upgrade Exit | Exit upgrade mode |
| `0x2010` | FW Program Info | Query firmware info |
| `0x2011` | FW Data Backup | Backup current firmware |
| `0x2012` | FW Update Request | Request firmware update |

## Print Flow

The complete print sequence:

1. **Connect** to the printer via BLE
2. **Discover services** and subscribe to notifications on the notify characteristic
3. **Query Image Support Info** (opcode `0x0002`, InfoType `0x00`) to auto-detect the printer model from response dimensions
4. **Prepare the image**: resize to model dimensions, JPEG compress, split into chunks (last chunk zero-padded to full chunk size)
5. **Send Download Start** (`0x1000`) with picture type, print option, and JPEG data size; wait for ACK
6. **Send Data chunks** (`0x1001`) with sequential chunk index (0, 1, 2…) and chunk data; wait for ACK after each chunk
7. **Send Download End** (`0x1002`); wait for ACK
8. **Send Print Image** (`0x1080`); wait for print status response (0 = success)
9. **Disconnect**

### Print Options

The Download Start command includes a `print_option` byte:

- `0x00` — Rich mode (vivid colors)
- `0x01` — Natural mode (classic film look)

## Model-Specific Parameters

| Model | Width | Height | Chunk Size | Max Image Size |
|-------|-------|--------|------------|----------------|
| Mini Link | 600 | 800 | 900 B | ~105 KB |
| Square Link | 800 | 800 | 1808 B | ~105 KB |
| Wide Link | 1260 | 840 | 900 B | ~105 KB |

Model is auto-detected from the Image Support Info response dimensions.

## Alternative Transports

The same packet protocol works over three transport layers:

| Transport | Platform | Notes |
|-----------|----------|-------|
| BLE GATT | iOS, macOS, Linux | Primary. MTU=182, packets fragmented. |
| RFCOMM/SPP | Android | Classic Bluetooth serial. No MTU fragmentation needed. |
| USB CDC ACM | Any | Printer appears as serial device (`/dev/ttyACM0`). Vendor `04cb`, Product `5019`. |

## References

- [jpwsutton/instax_api#21](https://github.com/jpwsutton/instax_api/issues/21) — Original BLE protocol reverse engineering thread
- [javl/InstaxBLE](https://github.com/javl/InstaxBLE) — Python implementation
- [linssenste/instax-link-web](https://github.com/linssenste/instax-link-web) — Web Bluetooth implementation
- [dgwilson/ESP32-Instax-Bridge](https://github.com/dgwilson/ESP32-Instax-Bridge) — ESP32 bridge
- [Reverse Engineering Guide](../development/reverse-engineering.md) — How to capture and analyze traffic for new devices
