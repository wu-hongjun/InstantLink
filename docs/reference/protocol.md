# BLE Protocol Reference

This documents the Instax Link BLE packet protocol that InstantLink currently implements over BLE GATT.

## BLE Service

| Item | UUID |
|------|------|
| Service | `70954782-2d83-473d-9e5f-81e1d02d5273` |
| Write Characteristic | `70954783-2d83-473d-9e5f-81e1d02d5273` |
| Notify Characteristic | `70954784-2d83-473d-9e5f-81e1d02d5273` |

## Packet Format

```text
[0x41 0x62] [length:2B] [opcode:2B] [payload...] [checksum:1B]
```

| Field | Size | Description |
|-------|------|-------------|
| Header | 2 bytes | Request: `0x41 0x62`, Response: `0x61 0x42` |
| Length | 2 bytes | Big-endian packet size including header and checksum |
| Opcode | 2 bytes | Command identifier |
| Payload | variable | Command-specific data |
| Checksum | 1 byte | `(255 - (sum_of_preceding_bytes & 255)) & 255` |

## Query Commands

All status queries use opcode `0x0002` with an `InfoType` selector byte.

| Opcode | Name | Payload | Description |
|--------|------|---------|-------------|
| `0x0001` | Device Info Service | SubIndex(1B) | Query a device-info string |
| `0x0002` | Support Function Info | InfoType(1B) | Query printer capabilities or status |

### Device Info Sub-Indices

| Sub-index | Field | Example |
|-----------|-------|---------|
| `0x00` | Manufacturer | `FUJIFILM` |
| `0x01` | Model | `SP-4` |
| `0x02` | Serial Number | `10458647` |
| `0x03` | Unknown version | `0000` |
| `0x04` | Hardware version | `0102` |
| `0x05` | Firmware version | `1.00` |

Response format: `[return_code] [sub_index] [string_length] [ASCII bytes...]`

### `InfoType` Values

| InfoType | Name | Response Data |
|----------|------|---------------|
| `0x00` | Image Support Info | Width(2B), Height(2B) |
| `0x01` | Battery Status | State(1B), Level(1B) |
| `0x02` | Printer Function Info | Film remaining in bits `0...3`, charging in bit `7` |
| `0x03` | Print Count | Print count(2B, big-endian) |

Response format: `[return_code] [info_type] [data...]`

## Image Transfer

| Opcode | Name | Payload | Response |
|--------|------|---------|----------|
| `0x1000` | Download Start | PictureType + PrintOption + PrintOption2 + Zero + ImageSize(4B) | ACK status |
| `0x1001` | Data | ChunkIndex(4B) + chunk data | ACK status |
| `0x1002` | Download End | none | ACK status |
| `0x1003` | Download Cancel | none | ACK status |
| `0x1080` | Print Image | none | Print status |

Success is model-aware. InstantLink accepts status `0` and each model's success code:

- Mini: `0`
- Mini Link 3: `16`
- Square: `12`
- Wide: `15`

Rejection codes currently mapped in the core:

- `178` no film
- `179` cover open
- `180` low battery
- `181` printer busy

## Power and LED Commands

| Opcode | Name | Description |
|--------|------|-------------|
| `0x0100` | Shut Down | Power off the printer |
| `0x0101` | Reset | Reset the printer |
| `0x3000` | XYZ Axis Info | Query accelerometer/orientation |
| `0x3001` | LED Pattern Settings | Set LED color or animation |
| `0x3010` | Additional Printer Info | Query additional printer info |

LED payload format:

```text
[when:1B] [frame_count:1B] [speed:1B] [repeat:1B] [B,G,R per frame...]
```

Colors are sent in **BGR** order.

## Print Flow

1. Connect to the printer over BLE
2. Discover services and subscribe to notifications
3. Query `Image Support Info`
4. Detect the model:
   - use DIS model hint `FI033` first for Mini Link 3
   - otherwise fall back to the reported width and height
5. Resize and JPEG-encode the image for the detected model
6. Send `Download Start` and wait for ACK
7. Send `Data` chunks, waiting for ACK after each chunk
8. Send `Download End` and wait for ACK
9. Send `Print Image` and accept `0` or the model-specific success code
10. Disconnect

## Model-Specific Parameters

| Model | Width | Height | Chunk Size | Max Image Size | Success Code | Notes |
|-------|-------|--------|------------|----------------|--------------|-------|
| Mini Link | 600 | 800 | 900 B | `105 KB` | `0` | Standard Mini behavior |
| Mini Link 3 | 600 | 800 | 900 B | `55 KB` | `16` | Uses DIS hint `FI033`, vertically flipped upload |
| Square Link | 800 | 800 | 1808 B | `105 KB` | `12` | Adds packet and pre-execute delays |
| Wide Link | 1260 | 840 | 900 B | `225 KB` | `15` | Wide-format image limit |

## Transport Notes

InstantLink's production runtime is BLE-only. The packet structure has also been observed over other transports during reverse engineering, but those transports are not implemented in this codebase.

| Transport | Status in InstantLink | Notes |
|-----------|------------------------|-------|
| BLE GATT | Implemented | Primary transport in `transport.rs` |
| RFCOMM/SPP | Not implemented | Protocol-level background only |
| USB CDC ACM | Not implemented | Protocol-level background only |

## References

- [jpwsutton/instax_api#21](https://github.com/jpwsutton/instax_api/issues/21)
- [javl/InstaxBLE](https://github.com/javl/InstaxBLE)
- [linssenste/instax-link-web](https://github.com/linssenste/instax-link-web)
- [dgwilson/ESP32-Instax-Bridge](https://github.com/dgwilson/ESP32-Instax-Bridge)
- [Reverse Engineering Guide](../development/reverse-engineering.md)
